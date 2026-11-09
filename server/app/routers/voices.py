"""목소리 확인: 화자별 대표 구간을 듣고 '이 목소리가 누구예요?'를 고른다. 클립별 포함/제외와 자막 고치기."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Asset, Clip, Space, Speaker
from app.pipeline.process import index_clips
from app.schemas import ClipList, ClipUpdate, SpeakerUpdate, VoiceReview, VoiceReviewAsset
from app.schemas import Clip as ClipOut
from app.schemas import Speaker as SpeakerOut
from app.security.auth import SpaceAccess, space_editor, space_reader
from app.services.assets import asset_out, clip_out
from app.services.spaces import space_counts

router = APIRouter(tags=["voices"])

SAMPLES_PER_SPEAKER = 3


def _refresh_review_flag(db: Session, asset: Asset) -> None:
    db.flush()
    roles = db.scalars(select(Speaker.role).where(Speaker.asset_id == asset.id)).all()
    asset.voice_reviewed = bool(roles) and all(r != "unknown" for r in roles)


def _consent(db: Session, space: Space) -> bool:
    from app.models import User

    owner = db.get(User, space.owner_id)
    return bool(owner and (owner.prefs or {}).get("consent_training_providers"))


@router.get("/spaces/{space_id}/voices", response_model=VoiceReview)
def voice_review(access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)) -> VoiceReview:
    space = access.space
    assets = db.scalars(
        select(Asset)
        .where(Asset.space_id == space.id, Asset.kind.in_(["audio", "video"]), Asset.status == "ready")
        .order_by(Asset.voice_reviewed, Asset.recorded_at.desc().nullslast(), Asset.created_at.desc())
    ).all()
    if not assets:
        return VoiceReview(person_name=space.person_name, assets=[], pending_count=0)
    asset_ids = [a.id for a in assets]
    speakers = db.scalars(select(Speaker).where(Speaker.asset_id.in_(asset_ids)).order_by(Speaker.created_at)).all()
    clips = db.scalars(select(Clip).where(Clip.asset_id.in_(asset_ids)).order_by(Clip.seq)).all()
    by_speaker: dict[str, list[Clip]] = defaultdict(list)
    for c in clips:
        if c.speaker_id:
            by_speaker[c.speaker_id].append(c)
    roles = {s.id: s.role for s in speakers}
    speakers_by_asset: dict[str, list[SpeakerOut]] = defaultdict(list)
    for s in speakers:
        mine = by_speaker.get(s.id, [])
        # 대표 구간: 자막이 있고 긴 것부터
        samples = sorted(mine, key=lambda c: (bool(c.text.strip()), c.end_sec - c.start_sec), reverse=True)
        speakers_by_asset[s.asset_id].append(
            SpeakerOut(
                id=s.id,
                asset_id=s.asset_id,
                label=s.label,
                role=s.role,  # type: ignore[arg-type]
                clip_count=len(mine),
                total_sec=round(sum(c.end_sec - c.start_sec for c in mine), 1),
                samples=[clip_out(c, roles.get(c.speaker_id or "")) for c in samples[:SAMPLES_PER_SPEAKER]],
            )
        )
    counts: dict[str, int] = defaultdict(int)
    for c in clips:
        counts[c.asset_id] += 1
    items = [
        VoiceReviewAsset(
            asset=asset_out(a, counts[a.id]),
            speakers=speakers_by_asset.get(a.id, []),
            diarized=a.diarized,
            needs_review=not a.voice_reviewed,
        )
        for a in assets
    ]
    return VoiceReview(
        person_name=space.person_name,
        assets=items,
        pending_count=sum(1 for i in items if i.needs_review),
    )


@router.patch("/spaces/{space_id}/speakers/{speaker_id}", response_model=SpeakerOut)
def set_speaker_role(
    speaker_id: str, body: SpeakerUpdate, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> SpeakerOut:
    speaker = db.get(Speaker, speaker_id)
    if speaker is None or speaker.space_id != access.space.id:
        raise ApiError(404, "not_found")
    speaker.role = body.role
    asset = db.get(Asset, speaker.asset_id)
    if asset:
        _refresh_review_flag(db, asset)
    access.space.index_version += 1
    db.commit()
    mine = db.scalars(select(Clip).where(Clip.speaker_id == speaker.id).order_by(Clip.seq)).all()
    return SpeakerOut(
        id=speaker.id,
        asset_id=speaker.asset_id,
        label=speaker.label,
        role=speaker.role,  # type: ignore[arg-type]
        clip_count=len(mine),
        total_sec=round(sum(c.end_sec - c.start_sec for c in mine), 1),
        samples=[],
    )


@router.get("/spaces/{space_id}/assets/{asset_id}/clips", response_model=ClipList)
def asset_clips(asset_id: str, access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)) -> ClipList:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.space_id != access.space.id:
        raise ApiError(404, "not_found")
    rows = db.execute(
        select(Clip, Speaker.role)
        .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
        .where(Clip.asset_id == asset.id)
        .order_by(Clip.seq)
    ).all()
    return ClipList(clips=[clip_out(c, role) for c, role in rows])


@router.patch("/spaces/{space_id}/clips/{clip_id}", response_model=ClipOut)
def update_clip(
    clip_id: str, body: ClipUpdate, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> ClipOut:
    clip = db.get(Clip, clip_id)
    if clip is None or clip.space_id != access.space.id:
        raise ApiError(404, "not_found")
    data = body.model_dump(exclude_unset=True)
    reindex = False
    if data.get("text") is not None:
        text = data["text"].strip()
        if text != clip.text:
            clip.text = text
            # 사용자가 고친 자막임을 표시한다(원래 자막은 text_original에 남는다)
            clip.text_edited = text != clip.text_original
            reindex = True
    if data.get("clear_override"):
        clip.include_override = None
    elif "include_override" in data and data["include_override"] is not None:
        clip.include_override = data["include_override"]
    if data.get("tags") is not None:
        clip.tags = list(dict.fromkeys(data["tags"]))[:6]
        reindex = True
    access.space.index_version += 1
    db.flush()
    if reindex:
        index_clips(db, access.space, clip_ids=[clip.id], consent=_consent(db, access.space))
    db.commit()
    role = db.scalar(select(Speaker.role).where(Speaker.id == clip.speaker_id)) if clip.speaker_id else None
    return clip_out(clip, role)


@router.get("/spaces/{space_id}/voices/summary")
def voice_summary(access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)) -> dict:
    c = space_counts(db, access.space.id)
    return {"pending_voice": c.pending_voice, "person_clips": c.person_clips}
