"""앱 안 알림(생일·기일·지난해 오늘). 밤 늦게(22시~8시, 한국 시간)는 새로 띄우지 않는다."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Response
from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Asset, Clip, Member, NoticeDismissal, Space, Speaker, User
from app.schemas import Notice, NoticeList
from app.security.auth import current_user
from app.services.spaces import included_expr

router = APIRouter(tags=["notices"])

KST = dt.timezone(dt.timedelta(hours=9))
QUIET_START = 22
QUIET_END = 8


def is_quiet(now: dt.datetime) -> bool:
    h = now.astimezone(KST).hour
    return h >= QUIET_START or h < QUIET_END


def _anniversary(d: dt.date, year: int) -> dt.date:
    try:
        return d.replace(year=year)
    except ValueError:  # 2월 29일
        return dt.date(year, 2, 28)


def build_notices(db: Session, user: User, now: dt.datetime) -> list[Notice]:
    if is_quiet(now):
        return []
    today = now.astimezone(KST).date()
    spaces = db.scalars(
        select(Space)
        .join(Member, Member.space_id == Space.id)
        .where(Member.user_id == user.id, Space.is_sample.is_(False))
    ).all()
    dismissed = set(db.scalars(select(NoticeDismissal.notice_id).where(NoticeDismissal.user_id == user.id)))
    out: list[Notice] = []
    for s in spaces:
        for kind, d in (("memorial", s.memorial_day), ("birthday", s.birthday)):
            if d is None:
                continue
            ann = _anniversary(d, today.year)
            days = (ann - today).days
            if days not in (0, 1):
                continue
            nid = f"{kind}:{s.id}:{ann.isoformat()}:{days}"
            if nid in dismissed:
                continue
            if kind == "memorial":
                title = "오늘은 기일이에요" if days == 0 else "내일은 기일이에요"
                msg = f"{s.person_name}을(를) 생각하는 날이에요. 듣고 싶을 때 천천히 들어도 괜찮아요."
            else:
                title = "오늘은 생신이에요" if days == 0 else "내일은 생신이에요"
                msg = f"{s.person_name}의 생신이에요. 함께 웃던 목소리를 꺼내 들어 볼까요?"
            out.append(Notice(id=nid, kind=kind, space_id=s.id, title=title, message=msg))
        has_otd = db.scalar(
            select(Clip.id)
            .join(Asset, Asset.id == Clip.asset_id)
            .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
            .where(
                Clip.space_id == s.id,
                included_expr(),
                extract("month", Asset.recorded_at) == today.month,
                extract("day", Asset.recorded_at) == today.day,
                extract("year", Asset.recorded_at) < today.year,
            )
            .limit(1)
        )
        nid = f"on_this_day:{s.id}:{today.isoformat()}"
        if has_otd and nid not in dismissed:
            out.append(
                Notice(
                    id=nid,
                    kind="on_this_day",
                    space_id=s.id,
                    title="지난해 오늘의 목소리",
                    message=f"{s.person_name}의 지난해 오늘 녹음이 있어요. 타임라인에서 들어 볼 수 있어요.",
                )
            )
    return out


@router.get("/notices", response_model=NoticeList)
def notices(user: User = Depends(current_user), db: Session = Depends(get_db)) -> NoticeList:
    return NoticeList(notices=build_notices(db, user, dt.datetime.now(dt.UTC)))


@router.post("/notices/{notice_id}/dismiss", status_code=204)
def dismiss(notice_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    if len(notice_id) > 120:
        raise ApiError(400, "invalid_input")
    exists = db.scalar(
        select(NoticeDismissal).where(
            NoticeDismissal.user_id == user.id, NoticeDismissal.notice_id == notice_id
        )
    )
    if exists is None:
        db.add(NoticeDismissal(user_id=user.id, notice_id=notice_id))
        db.commit()
    return Response(status_code=204)
