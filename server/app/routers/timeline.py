"""추억 타임라인: 날짜별 클립과 사진, 주제 필터, 즐겨찾기, '1년 전 오늘'."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Asset, Clip, Favorite, Speaker
from app.schemas import Timeline, TimelineDay, TimelineItem
from app.security.auth import SpaceAccess, space_reader
from app.services.assets import clip_cards, date_label, photo_ref
from app.services.spaces import included_expr

router = APIRouter(tags=["timeline"])

KST = dt.timezone(dt.timedelta(hours=9))
MAX_CLIPS = 600
WEEKDAYS = "월화수목금토일"


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def _day_label(d: dt.date | None) -> str:
    if d is None:
        return "날짜 모름"
    return f"{date_label(d)} ({WEEKDAYS[d.weekday()]})"


@router.get("/spaces/{space_id}/timeline", response_model=Timeline)
def timeline(
    tag: str | None = Query(None, max_length=20),
    favorites: bool = False,
    year: int | None = Query(None, ge=1900, le=2100),
    access: SpaceAccess = Depends(space_reader),
    db: Session = Depends(get_db),
) -> Timeline:
    space = access.space
    user_id = access.user.id if access.user else None
    q = (
        select(Clip.id, Clip.tags, Asset.recorded_at)
        .join(Asset, Asset.id == Clip.asset_id)
        .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
        .where(Clip.space_id == space.id, included_expr())
        .order_by(Asset.recorded_at.desc().nullslast(), Asset.created_at.desc(), Clip.seq)
    )
    rows = db.execute(q).all()
    tag_counts = Counter(t for _, tags, _ in rows for t in (tags or []))
    fav_ids: set[str] = set()
    if user_id:
        fav_ids = set(db.scalars(select(Favorite.clip_id).where(Favorite.user_id == user_id)))

    def keep(cid: str, tags: list[str] | None, d: dt.date | None) -> bool:
        if tag and tag not in (tags or []):
            return False
        if favorites and cid not in fav_ids:
            return False
        if year and (d is None or d.year != year):
            return False
        return True

    clip_rows = [(cid, d) for cid, tags, d in rows if keep(cid, tags, d)][:MAX_CLIPS]
    photos = []
    if not tag and not favorites:
        pq = select(Asset).where(Asset.space_id == space.id, Asset.kind == "photo", Asset.status == "ready")
        if year:
            pq = pq.where(func.extract("year", Asset.recorded_at) == year)
        photos = db.scalars(pq).all()

    cards = {
        c.clip_id: c
        for c in clip_cards(db, space.id, [cid for cid, _ in clip_rows], user_id, with_photos=False)
    }
    by_day: dict[dt.date | None, list[TimelineItem]] = defaultdict(list)
    for cid, d in clip_rows:
        if cid in cards:
            by_day[d].append(TimelineItem(kind="clip", clip=cards[cid]))
    for p in photos:
        by_day[p.recorded_at].append(TimelineItem(kind="photo", photo=photo_ref(p)))

    dated = sorted((d for d in by_day if d is not None), reverse=True)
    days = [TimelineDay(date=d, label=_day_label(d), items=by_day[d]) for d in dated]
    if None in by_day:
        days.append(TimelineDay(date=None, label="날짜 모름", items=by_day[None]))

    today = today_kst()
    on_this_day: list[TimelineItem] = []
    for d in dated:
        if (d.month, d.day) == (today.month, today.day) and d.year < today.year:
            on_this_day.extend(by_day[d])
    return Timeline(
        days=days,
        on_this_day=on_this_day[:6],
        tag_counts=dict(tag_counts.most_common()),
        total=sum(len(v) for v in by_day.values()),
    )
