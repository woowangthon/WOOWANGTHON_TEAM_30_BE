"""대화 API, 음성으로 말 걸기(받아쓰기), 즐겨찾기."""

from __future__ import annotations

import datetime as dt
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai import registry
from app.ai.base import ProviderError
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Clip, Favorite, UsageCounter, User
from app.routers.assets import read_limited
from app.routers.auth import client_ip
from app.schemas import CallRequest, CallResponse, ChatRequest, ChatResponse, FavoriteUpdate, TranscribeResponse
from app.security.auth import SpaceAccess, current_user, space_reader
from app.services.chat import answer
from app.services.talk import talk as persona_talk

router = APIRouter(tags=["chat"])

KST = dt.timezone(dt.timedelta(hours=9))
_sample_hits: dict[str, deque[float]] = defaultdict(deque)


def _sample_rate_limit(ip: str) -> None:
    limit = get_settings().sample_chat_per_minute
    now = time.monotonic()
    q = _sample_hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        raise ApiError(429, "rate_limited")
    q.append(now)


def _count_chat(db: Session, user: User) -> int | None:
    """하루 대화 횟수를 세고 남은 횟수를 돌려준다(제한 없으면 None)."""
    limit = get_settings().effective_chat_daily_limit
    today = dt.datetime.now(KST).date()
    stmt = insert(UsageCounter).values(user_id=user.id, day=today, chats=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UsageCounter.user_id, UsageCounter.day], set_={"chats": UsageCounter.chats + 1}
    ).returning(UsageCounter.chats)
    used = int(db.execute(stmt).scalar_one())
    if not limit:
        return None
    if used > limit:
        raise ApiError(429, "chat_limit_reached")
    return limit - used


def _consent(user: User | None) -> bool:
    return bool(user and (user.prefs or {}).get("consent_training_providers"))


@router.post("/spaces/{space_id}/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    request: Request,
    access: SpaceAccess = Depends(space_reader),
    db: Session = Depends(get_db),
) -> ChatResponse:
    remaining = None
    if access.user is None:
        _sample_rate_limit(client_ip(request))
    else:
        remaining = _count_chat(db, access.user)
        db.commit()
    owner_consent = False
    if not access.space.is_sample:
        owner = db.get(User, access.space.owner_id)
        owner_consent = _consent(owner)
    result = answer(
        db,
        access.space,
        body.message,
        user_id=access.user.id if access.user else None,
        consent=owner_consent,
    )
    resp = result.response
    resp.remaining_today = remaining
    return resp


@router.post("/spaces/{space_id}/talk", response_model=CallResponse)
def talk(
    body: CallRequest,
    request: Request,
    access: SpaceAccess = Depends(space_reader),
    db: Session = Depends(get_db),
) -> CallResponse:
    """그 사람과 메신저처럼 대화: 답장 하나 (원본 녹음 또는 근거가 붙은 AI 답)."""
    remaining = None
    if access.user is None:
        _sample_rate_limit(client_ip(request))
    else:
        remaining = _count_chat(db, access.user)
        db.commit()
    owner_consent = False
    if not access.space.is_sample:
        owner_consent = _consent(db.get(User, access.space.owner_id))
    resp = persona_talk(
        db,
        access.space,
        body.message,
        body.history,
        user_id=access.user.id if access.user else None,
        consent=owner_consent,
    )
    resp.remaining_today = remaining
    return resp


@router.post("/spaces/{space_id}/transcribe", response_model=TranscribeResponse)
def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    access: SpaceAccess = Depends(space_reader),
) -> TranscribeResponse:
    """음성으로 말 걸기: 브라우저 녹음을 받아쓰기만 하고 저장하지 않는다."""
    if access.user is None:
        _sample_rate_limit(client_ip(request))
    # 말을 거는 사람 본인의 목소리라 샘플 공간이어도 실제 사용자 자료로 다룬다
    stt, _ = registry.build("stt", consent=_consent(access.user), is_sample=False)
    if not getattr(stt, "live", False) or not hasattr(stt, "transcribe_short"):
        raise ApiError(503, "stt_unavailable")
    data = read_limited(audio, 10 * 1024 * 1024)
    if not data:
        raise ApiError(400, "empty_file")
    suffix = Path(audio.filename or "voice.webm").suffix[:8] or ".webm"
    with tempfile.TemporaryDirectory(prefix="yeoun-voice-") as tmp:
        path = Path(tmp) / f"voice{suffix}"
        path.write_bytes(data)
        try:
            text = stt.transcribe_short(path)
        except ProviderError as e:
            raise ApiError(502, "stt_failed") from e
        except Exception as e:  # ffmpeg 변환 실패 등
            raise ApiError(400, "stt_failed") from e
    return TranscribeResponse(text=text[:500])


@router.put("/spaces/{space_id}/clips/{clip_id}/favorite", response_model=FavoriteUpdate)
def set_favorite(
    clip_id: str,
    body: FavoriteUpdate,
    access: SpaceAccess = Depends(space_reader),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FavoriteUpdate:
    clip = db.get(Clip, clip_id)
    if clip is None or clip.space_id != access.space.id:
        raise ApiError(404, "not_found")
    if body.favorite:
        db.execute(
            insert(Favorite)
            .values(user_id=user.id, clip_id=clip.id)
            .on_conflict_do_nothing(index_elements=[Favorite.user_id, Favorite.clip_id])
        )
    else:
        db.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.clip_id == clip.id))
    db.commit()
    return FavoriteUpdate(favorite=body.favorite)
