"""가족 초대와 권한 (소유자/편집/보기). 초대 링크는 만료되는 1회용 토큰."""

from __future__ import annotations

import datetime as dt
import secrets

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import web_base_url
from app.db import get_db
from app.errors import ApiError
from app.models import Invite, Member, Space, User, utcnow
from app.schemas import Invite as InviteOut
from app.schemas import InviteCreate, InvitePreview, MemberList, MemberUpdate
from app.schemas import Member as MemberOut
from app.security.auth import SpaceAccess, current_user, space_owner, space_reader
from app.security.crypto import token_hash

router = APIRouter(tags=["members"])

INVITE_DAYS = 7


def _members(db: Session, space_id: str) -> list[MemberOut]:
    rows = db.execute(
        select(Member, User)
        .join(User, User.id == Member.user_id)
        .where(Member.space_id == space_id)
        .order_by(Member.created_at)
    ).all()
    return [MemberOut(user_id=u.id, display_name=u.display_name, email=u.email, role=m.role) for m, u in rows]


def _invites(db: Session, space_id: str) -> list[InviteOut]:
    rows = db.scalars(
        select(Invite).where(
            Invite.space_id == space_id, Invite.used_at.is_(None), Invite.expires_at > utcnow()
        )
    ).all()
    return [InviteOut(id=i.id, role=i.role, url=None, expires_at=i.expires_at) for i in rows]


@router.get("/spaces/{space_id}/members", response_model=MemberList)
def list_members(access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)) -> MemberList:
    if access.space.is_sample:
        return MemberList(members=[], invites=[])
    invites = _invites(db, access.space.id) if access.role == "owner" else []
    return MemberList(members=_members(db, access.space.id), invites=invites)


@router.post("/spaces/{space_id}/invites", response_model=InviteOut, status_code=201)
def create_invite(
    body: InviteCreate,
    request: Request,
    access: SpaceAccess = Depends(space_owner),
    db: Session = Depends(get_db),
) -> InviteOut:
    if body.role == "owner":
        raise ApiError(400, "invalid_input", "초대는 편집 또는 보기 권한으로만 할 수 있어요.")
    token = secrets.token_urlsafe(24)
    user = access.user
    assert user is not None
    inv = Invite(
        space_id=access.space.id,
        token_hash=token_hash(token),
        role=body.role,
        created_by=user.id,
        expires_at=utcnow() + dt.timedelta(days=INVITE_DAYS),
    )
    db.add(inv)
    db.commit()
    url = f"{web_base_url(request.headers.get('origin'))}/invite/{token}"
    return InviteOut(id=inv.id, role=inv.role, url=url, expires_at=inv.expires_at)  # type: ignore[arg-type]


@router.delete("/spaces/{space_id}/invites/{invite_id}", status_code=204)
def cancel_invite(
    invite_id: str, access: SpaceAccess = Depends(space_owner), db: Session = Depends(get_db)
) -> Response:
    inv = db.get(Invite, invite_id)
    if inv is None or inv.space_id != access.space.id:
        raise ApiError(404, "not_found")
    db.delete(inv)
    db.commit()
    return Response(status_code=204)


@router.patch("/spaces/{space_id}/members/{user_id}", response_model=MemberOut)
def change_role(
    user_id: str,
    body: MemberUpdate,
    access: SpaceAccess = Depends(space_owner),
    db: Session = Depends(get_db),
) -> MemberOut:
    m = db.scalar(select(Member).where(Member.space_id == access.space.id, Member.user_id == user_id))
    if m is None:
        raise ApiError(404, "not_found")
    if m.role == "owner" or body.role == "owner":
        raise ApiError(400, "cannot_remove_owner", "소유자 권한은 바꿀 수 없어요.")
    m.role = body.role
    db.commit()
    u = db.get(User, user_id)
    assert u is not None
    return MemberOut(user_id=u.id, display_name=u.display_name, email=u.email, role=m.role)  # type: ignore[arg-type]


@router.delete("/spaces/{space_id}/members/{user_id}", status_code=204)
def remove_member(
    user_id: str, access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)
) -> Response:
    """소유자는 다른 가족을 내보낼 수 있고, 가족은 스스로 나갈 수 있다."""
    if access.user is None or access.space.is_sample:
        raise ApiError(403, "forbidden")
    if access.role != "owner" and access.user.id != user_id:
        raise ApiError(403, "owner_required")
    m = db.scalar(select(Member).where(Member.space_id == access.space.id, Member.user_id == user_id))
    if m is None:
        raise ApiError(404, "not_found")
    if m.role == "owner":
        raise ApiError(400, "cannot_remove_owner")
    db.delete(m)
    db.commit()
    return Response(status_code=204)


def _valid_invite(db: Session, token: str) -> Invite:
    inv = (
        db.scalar(select(Invite).where(Invite.token_hash == token_hash(token))) if len(token) < 100 else None
    )
    if inv is None or inv.used_at is not None or inv.expires_at < utcnow():
        raise ApiError(410, "invite_invalid")
    return inv


@router.get("/invites/{token}", response_model=InvitePreview)
def preview_invite(token: str, db: Session = Depends(get_db)) -> InvitePreview:
    inv = _valid_invite(db, token)
    space = db.get(Space, inv.space_id)
    inviter = db.get(User, inv.created_by)
    assert space is not None
    return InvitePreview(
        space_name=space.name,
        inviter_name=inviter.display_name if inviter else "가족",
        role=inv.role,  # type: ignore[arg-type]
    )


@router.post("/invites/{token}/accept")
def accept_invite(token: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    inv = _valid_invite(db, token)
    existing = db.scalar(select(Member).where(Member.space_id == inv.space_id, Member.user_id == user.id))
    if existing is None:
        db.add(Member(space_id=inv.space_id, user_id=user.id, role=inv.role))
    inv.used_at = utcnow()
    db.commit()
    return {"space_id": inv.space_id}
