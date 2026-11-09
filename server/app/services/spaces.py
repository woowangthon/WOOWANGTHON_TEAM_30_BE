from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Asset, Clip, Member, Space, Speaker, User
from app.schemas import Space as SpaceOut
from app.schemas import SpaceCounts, SpaceCreate
from app.security import crypto
from app.storage import blobstore


def included_expr():
    """클립이 대화에 쓰이는지: 클립별 설정이 있으면 그것, 없으면 화자가 '그 사람'인지."""
    return or_(
        Clip.include_override.is_(True),
        and_(Clip.include_override.is_(None), Speaker.role == "person"),
    )


def create_space(db: Session, owner: User, body: SpaceCreate, *, is_sample: bool = False) -> Space:
    space = Space(
        owner_id=owner.id,
        name=body.name.strip(),
        person_name=body.person_name.strip(),
        relationship=(body.relationship or "").strip() or None,
        birthday=body.birthday,
        memorial_day=body.memorial_day,
        note=body.note,
        is_sample=is_sample,
        wrapped_key=b"",
    )
    db.add(space)
    db.flush()
    space.wrapped_key = crypto.wrap_key(crypto.new_data_key(), space.id)
    db.add(Member(space_id=space.id, user_id=owner.id, role="owner"))
    db.flush()
    return space


def space_counts(db: Session, space_id: str) -> SpaceCounts:
    asset_rows = db.execute(
        select(Asset.kind, Asset.status, Asset.voice_reviewed, Asset.source).where(Asset.space_id == space_id)
    ).all()
    assets = len(asset_rows)
    photos = sum(1 for r in asset_rows if r.kind == "photo")
    processing = sum(1 for r in asset_rows if r.status in ("uploaded", "queued", "processing"))
    pending_voice = sum(
        1
        for r in asset_rows
        if r.kind in ("audio", "video")
        and r.status == "ready"
        and not r.voice_reviewed
        and r.source == "upload"
    )
    clips = db.scalar(select(func.count()).select_from(Clip).where(Clip.space_id == space_id)) or 0
    person_clips = (
        db.scalar(
            select(func.count())
            .select_from(Clip)
            .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
            .where(Clip.space_id == space_id, included_expr())
        )
        or 0
    )
    return SpaceCounts(
        assets=assets,
        clips=clips,
        person_clips=person_clips,
        photos=photos,
        pending_voice=pending_voice,
        processing=processing,
    )


def space_out(db: Session, space: Space, role: str) -> SpaceOut:
    quota = get_settings().effective_space_quota_mb * 1024 * 1024
    return SpaceOut(
        id=space.id,
        name=space.name,
        person_name=space.person_name,
        relationship=space.relationship,
        birthday=space.birthday,
        memorial_day=space.memorial_day,
        note=space.note,
        is_sample=space.is_sample,
        role=role,  # type: ignore[arg-type]
        counts=space_counts(db, space.id),
        storage_bytes=blobstore.space_usage(db, space.id),
        storage_limit_bytes=0 if space.is_sample else quota,
        created_at=space.created_at,
    )
