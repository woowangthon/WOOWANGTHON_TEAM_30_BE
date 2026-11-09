"""미리 남기기: 질문 카드를 골라 로그인 없이 쓰는 녹음 링크(만료되는 1회용 토큰)를 보낸다.

- 토큰은 서버에 sha256만 저장하고, 링크 주소는 만들 때 한 번만 돌려준다.
- 녹음하는 분은 동의 문구를 본 뒤에만 녹음을 보낼 수 있다.
- '다 했어요'를 누르거나 기간이 지나면 링크는 더 이상 쓸 수 없다.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
import time
from collections import defaultdict, deque
from functools import lru_cache

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SHARED_DIR, get_settings, web_base_url
from app.db import get_db
from app.errors import ApiError
from app.models import Asset, RecordingLink, Space, User, utcnow
from app.routers.assets import check_quotas, create_asset, read_limited
from app.routers.auth import client_ip
from app.schemas import (
    LinkQuestion,
    QuestionDeck,
    RecorderSession,
    RecordingLinkCreate,
    RecordingLinkList,
)
from app.schemas import RecordingLink as LinkOut
from app.security.auth import SpaceAccess, space_editor
from app.security.crypto import token_hash
from app.services.deletion import delete_asset_completely

router = APIRouter(tags=["ahead"])

RECORDING_EXTS = {"webm", "ogg", "m4a", "mp4", "mp3", "wav", "aac", "3gp", "opus"}
_hits: dict[str, deque[float]] = defaultdict(deque)


@lru_cache
def deck() -> QuestionDeck:
    data = json.loads((SHARED_DIR / "question-cards.json").read_text(encoding="utf-8"))
    return QuestionDeck(categories=data["categories"], cards=data["cards"])


def _rate(key: str, limit: int = 60, window: float = 600) -> None:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise ApiError(429, "rate_limited")
    q.append(now)


def _status(link: RecordingLink) -> str:
    if link.status == "active" and link.expires_at < utcnow():
        return "expired"
    return link.status


def _answered(db: Session, link: RecordingLink) -> dict[str, str]:
    rows = db.execute(select(Asset.question_id, Asset.id).where(Asset.link_id == link.id)).all()
    return {q: a for q, a in rows if q}


def link_out(db: Session, link: RecordingLink, url: str | None = None) -> LinkOut:
    answered = _answered(db, link)
    questions = [
        LinkQuestion(id=q["id"], text=q["text"], answered=q["id"] in answered, asset_id=answered.get(q["id"]))
        for q in link.questions
    ]
    return LinkOut(
        id=link.id,
        url=url,
        status=_status(link),  # type: ignore[arg-type]
        sender_name=link.sender_name,
        questions=questions,
        answered_count=sum(1 for q in questions if q.answered),
        expires_at=link.expires_at,
        created_at=link.created_at,
    )


def consent_text(link: RecordingLink, space: Space) -> str:
    who = link.sender_name or "보낸 분"
    return (
        f"이 녹음은 {who}님의 '여운' 추억 공간에 원본 그대로 보관돼요. {who}님과 {who}님이 초대한 가족만 들을 수 있어요. "
        "여운은 이 목소리로 새 말이나 새 음성을 만들지 않아요. 나중에 찾기 쉽도록 녹음을 글자로 옮기는 데 "
        "음성 인식 서비스를 쓸 수 있어요. 원하시면 언제든 보낸 분께 지워 달라고 하실 수 있어요."
    )


@router.get("/questions", response_model=QuestionDeck)
def questions() -> QuestionDeck:
    return deck()


@router.get("/spaces/{space_id}/links", response_model=RecordingLinkList)
def list_links(
    access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> RecordingLinkList:
    links = db.scalars(
        select(RecordingLink)
        .where(RecordingLink.space_id == access.space.id)
        .order_by(RecordingLink.created_at.desc())
    ).all()
    return RecordingLinkList(links=[link_out(db, link) for link in links])


@router.post("/spaces/{space_id}/links", response_model=LinkOut, status_code=201)
def create_link(
    body: RecordingLinkCreate,
    request: Request,
    access: SpaceAccess = Depends(space_editor),
    db: Session = Depends(get_db),
) -> LinkOut:
    cards = {c.id: c for c in deck().cards}
    picked: list[dict] = []
    for qid in dict.fromkeys(body.question_ids):
        if qid not in cards:
            raise ApiError(400, "invalid_input", "없는 질문 카드가 섞여 있어요.")
        picked.append({"id": qid, "text": cards[qid].text})
    for i, text in enumerate(body.custom_questions or []):
        t = text.strip()
        if t:
            picked.append({"id": f"c{i + 1}", "text": t})
    if not picked:
        raise ApiError(400, "invalid_input", "질문을 하나 이상 골라 주세요.")
    if len(picked) > 20:
        raise ApiError(400, "invalid_input", "질문은 20개까지 보낼 수 있어요.")
    token = secrets.token_urlsafe(24)
    user = access.user
    assert user is not None
    link = RecordingLink(
        space_id=access.space.id,
        token_hash=token_hash(token),
        created_by=user.id,
        sender_name=(body.sender_name or user.display_name or "").strip()[:40] or None,
        message=(body.message or "").strip()[:300] or None,
        questions=picked,
        status="active",
        expires_at=utcnow() + dt.timedelta(days=body.expires_days),
    )
    db.add(link)
    db.commit()
    url = f"{web_base_url(request.headers.get('origin'))}/r/{token}"
    return link_out(db, link, url=url)


@router.post("/spaces/{space_id}/links/{link_id}/revoke", response_model=LinkOut)
def revoke_link(
    link_id: str, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> LinkOut:
    link = db.get(RecordingLink, link_id)
    if link is None or link.space_id != access.space.id:
        raise ApiError(404, "not_found")
    if link.status == "active":
        link.status = "revoked"
    db.commit()
    return link_out(db, link)


# ---------------------------------------------------------------- 녹음하는 쪽 (로그인 없음)


def _active_link(db: Session, token: str) -> RecordingLink:
    if len(token) > 100:
        raise ApiError(404, "link_expired")
    link = db.scalar(select(RecordingLink).where(RecordingLink.token_hash == token_hash(token)))
    if link is None or _status(link) != "active":
        raise ApiError(410 if link else 404, "link_expired")
    return link


@router.get("/record/{token}", response_model=RecorderSession)
def recorder_session(token: str, request: Request, db: Session = Depends(get_db)) -> RecorderSession:
    _rate(f"rec:{client_ip(request)}", limit=120)
    link = _active_link(db, token)
    space = db.get(Space, link.space_id)
    assert space is not None
    answered = _answered(db, link)
    return RecorderSession(
        sender_name=link.sender_name,
        message=link.message,
        questions=[
            LinkQuestion(id=q["id"], text=q["text"], answered=q["id"] in answered) for q in link.questions
        ],
        expires_at=link.expires_at,
        consent_text=consent_text(link, space),
        max_seconds=get_settings().recording_max_seconds,
    )


@router.post("/record/{token}/consent", status_code=204)
def recorder_consent(token: str, request: Request, db: Session = Depends(get_db)) -> Response:
    _rate(f"rec:{client_ip(request)}", limit=120)
    link = _active_link(db, token)
    if link.consent_at is None:
        link.consent_at = utcnow()
    db.commit()
    return Response(status_code=204)


@router.post("/record/{token}/answers", response_model=LinkQuestion, status_code=201)
def recorder_answer(
    token: str,
    request: Request,
    question_id: str = Form(..., max_length=40),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> LinkQuestion:
    _rate(f"rec-up:{client_ip(request)}", limit=40)
    link = _active_link(db, token)
    if link.consent_at is None:
        raise ApiError(403, "consent_needed")
    question = next((q for q in link.questions if q["id"] == question_id), None)
    if question is None:
        raise ApiError(400, "invalid_input", "없는 질문이에요.")
    filename = (audio.filename or "answer.webm").rsplit("/", 1)[-1]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    if ext not in RECORDING_EXTS:
        ext = "webm"
    data = read_limited(audio, 12 * 1024 * 1024)
    if len(data) < 200:
        raise ApiError(400, "empty_file", "녹음이 비어 있어요. 다시 녹음해 주세요.")
    space = db.get(Space, link.space_id)
    assert space is not None
    sender = db.get(User, link.created_by)
    # 같은 질문을 다시 녹음하면 예전 녹음을 지운다 (보내기 전 '다시 하기')
    for old in db.scalars(
        select(Asset).where(Asset.link_id == link.id, Asset.question_id == question_id)
    ).all():
        delete_asset_completely(db, old)
    check_quotas(db, space, sender, len(data))
    asset = create_asset(
        db,
        space,
        data=data,
        filename=f"미리 남기기 - {question['text'][:40]}.{ext}",
        ext=ext,
        kind="audio",
        source="ahead",
        origin="ahead",
        uploaded_by=None,
        question_id=question_id,
        question_text=question["text"],
        link_id=link.id,
    )
    asset.recorded_at = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    asset.date_source = "metadata"
    if sender is not None:
        sender.upload_bytes_total += len(data)
    db.commit()
    return LinkQuestion(id=question_id, text=question["text"], answered=True, asset_id=None)


@router.post("/record/{token}/complete", status_code=204)
def recorder_complete(token: str, request: Request, db: Session = Depends(get_db)) -> Response:
    _rate(f"rec:{client_ip(request)}", limit=120)
    link = _active_link(db, token)
    link.status = "completed"
    link.completed_at = utcnow()
    db.commit()
    return Response(status_code=204)
