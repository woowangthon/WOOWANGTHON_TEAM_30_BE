"""자료·클립을 API 응답 모양으로 바꾸기."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, Clip, Favorite, Speaker
from app.schemas import Asset as AssetOut
from app.schemas import AssetStage, ClipCard, ErrorBody, PhotoRef
from app.schemas import Clip as ClipOut
from app.security.media_urls import media_url

ORIGIN_LABELS = {
    "call": "통화 녹음",
    "video": "동영상",
    "voice_message": "음성 메시지",
    "ahead": "미리 남기기",
    "other": "녹음",
}


def date_label(d: dt.date | None) -> str:
    if d is None:
        return "날짜 모름"
    return f"{d.year}년 {d.month}월 {d.day}일"


def source_label(asset: Asset) -> str:
    base = ORIGIN_LABELS.get(asset.origin, "녹음")
    if asset.recorded_at:
        return f"{base} · {asset.recorded_at.year}년 {asset.recorded_at.month}월"
    return base


def asset_out(asset: Asset, clip_count: int = 0) -> AssetOut:
    error = None
    if asset.status == "failed" and asset.error_code:
        error = ErrorBody(code=asset.error_code, message_ko=asset.error_message or "처리하지 못했어요.")
    return AssetOut(
        id=asset.id,
        kind=asset.kind,  # type: ignore[arg-type]
        source=asset.source,  # type: ignore[arg-type]
        origin=asset.origin,  # type: ignore[arg-type]
        filename=asset.filename,
        size_bytes=asset.size_bytes,
        duration_sec=asset.duration_sec,
        recorded_at=asset.recorded_at,
        date_source=asset.date_source,  # type: ignore[arg-type]
        status=asset.status,  # type: ignore[arg-type]
        stages=[AssetStage(**s) for s in (asset.stages or [])],
        progress=asset.progress or 0.0,
        error=error,
        clip_count=clip_count,
        thumb_url=media_url("p", asset.id) if asset.kind == "photo" and asset.thumb_key else None,
        created_at=asset.created_at,
    )


def clip_counts(db: Session, asset_ids: list[str]) -> dict[str, int]:
    if not asset_ids:
        return {}
    rows = db.execute(
        select(Clip.asset_id, func.count()).where(Clip.asset_id.in_(asset_ids)).group_by(Clip.asset_id)
    ).all()
    return {a: n for a, n in rows}


def clip_audio(clip: Clip) -> tuple[str | None, str]:
    if clip.audio_status == "ready" and clip.audio_key:
        return media_url("c", clip.id), "ready"
    return None, clip.audio_status if clip.audio_status in ("placeholder", "missing") else "missing"


def effective_included(clip: Clip, speaker_role: str | None) -> bool:
    if clip.include_override is not None:
        return clip.include_override
    return speaker_role == "person"


def clip_out(clip: Clip, speaker_role: str | None) -> ClipOut:
    url, status = clip_audio(clip)
    return ClipOut(
        id=clip.id,
        asset_id=clip.asset_id,
        speaker_id=clip.speaker_id,
        start_sec=clip.start_sec,
        end_sec=clip.end_sec,
        text=clip.text,
        text_edited=clip.text_edited,
        tags=clip.tags or [],
        included=effective_included(clip, speaker_role),
        include_override=clip.include_override,
        audio_url=url,
        audio_status=status,  # type: ignore[arg-type]
        confidence=clip.confidence,
    )


def photos_by_date(db: Session, space_id: str, dates: set[dt.date]) -> dict[dt.date, list[PhotoRef]]:
    if not dates:
        return {}
    rows = db.scalars(
        select(Asset)
        .where(
            Asset.space_id == space_id,
            Asset.kind == "photo",
            Asset.status == "ready",
            Asset.recorded_at.in_(dates),
        )
        .order_by(Asset.created_at)
    ).all()
    out: dict[dt.date, list[PhotoRef]] = defaultdict(list)
    for a in rows:
        if a.recorded_at and len(out[a.recorded_at]) < 4:
            out[a.recorded_at].append(photo_ref(a))
    return out


def photo_ref(a: Asset) -> PhotoRef:
    return PhotoRef(asset_id=a.id, url=media_url("p", a.id), date=a.recorded_at, caption=a.caption)


def clip_cards(
    db: Session,
    space_id: str,
    clip_ids: list[str],
    user_id: str | None,
    reasons: dict[str, str | None] | None = None,
    with_photos: bool = True,
) -> list[ClipCard]:
    """클립 카드: 원문 자막·날짜·출처·같은 날 사진. transcript는 언제나 DB의 자막 그대로다."""
    if not clip_ids:
        return []
    rows = db.execute(
        select(Clip, Asset)
        .join(Asset, Asset.id == Clip.asset_id)
        .where(Clip.id.in_(clip_ids), Clip.space_id == space_id)
    ).all()
    by_id = {c.id: (c, a) for c, a in rows}
    favs: set[str] = set()
    if user_id:
        favs = set(
            db.scalars(
                select(Favorite.clip_id).where(Favorite.user_id == user_id, Favorite.clip_id.in_(clip_ids))
            )
        )
    photos = (
        photos_by_date(db, space_id, {a.recorded_at for _, a in rows if a.recorded_at}) if with_photos else {}
    )
    cards = []
    for cid in clip_ids:
        if cid not in by_id:
            continue
        c, a = by_id[cid]
        url, status = clip_audio(c)
        cards.append(
            ClipCard(
                clip_id=c.id,
                transcript=c.text,
                date=a.recorded_at,
                date_label=date_label(a.recorded_at),
                source_label=source_label(a),
                audio_url=url,
                audio_status=status,  # type: ignore[arg-type]
                start_sec=c.start_sec,
                end_sec=c.end_sec,
                photos=photos.get(a.recorded_at, []) if a.recorded_at else [],
                question=a.question_text,
                tags=c.tags or [],
                favorite=c.id in favs,
                reason=(reasons or {}).get(c.id),
            )
        )
    return cards


def speaker_roles(db: Session, speaker_ids: list[str]) -> dict[str, str]:
    if not speaker_ids:
        return {}
    return dict(db.execute(select(Speaker.id, Speaker.role).where(Speaker.id.in_(speaker_ids))).all())
