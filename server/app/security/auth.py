"""로그인 세션과 공간 접근 권한."""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Member, Space, User, UserSession, utcnow
from app.security.crypto import token_hash

COOKIE_NAME = "yeoun_session"
ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}

_hasher = PasswordHasher()
# 존재하지 않는 이메일로 로그인할 때도 같은 시간이 걸리게 하는 더미 해시
_DUMMY_HASH = _hasher.hash("yeoun-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_verify_time(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def create_session(db: Session, user: User, response: Response) -> str:
    s = get_settings()
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        UserSession(
            id=token_hash(token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + dt.timedelta(days=s.session_days),
        )
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=s.session_days * 86400,
        httponly=True,
        secure=s.secure_cookies,
        samesite="lax",
        path="/",
    )
    return token


def clear_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        sess = db.get(UserSession, token_hash(token))
        if sess:
            db.delete(sess)
    response.delete_cookie(COOKIE_NAME, path="/")


def _user_from_request(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 200:
        return None
    sess = db.get(UserSession, token_hash(token))
    now = utcnow()
    if sess is None or sess.expires_at < now:
        return None
    if (now - sess.last_seen_at).total_seconds() > 3600:
        sess.last_seen_at = now
    user = db.get(User, sess.user_id)
    if user is None or user.is_system:
        return None
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return _user_from_request(request, db)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _user_from_request(request, db)
    if user is None:
        raise ApiError(401, "unauthorized")
    return user


@dataclass
class SpaceAccess:
    space: Space
    role: str  # owner | editor | viewer
    user: User | None

    @property
    def is_sample(self) -> bool:
        return self.space.is_sample

    def require(self, role: str) -> None:
        if self.space.is_sample and role != "viewer":
            raise ApiError(403, "sample_read_only")
        if ROLE_RANK[self.role] < ROLE_RANK[role]:
            raise ApiError(403, "owner_required" if role == "owner" else "forbidden")


def get_space_access(db: Session, space_id: str, user: User | None) -> SpaceAccess:
    space = db.get(Space, space_id)
    if space is None:
        raise ApiError(404, "not_found")
    if space.is_sample:
        return SpaceAccess(space=space, role="viewer", user=user)
    if user is None:
        raise ApiError(401, "unauthorized")
    member = db.scalar(select(Member).where(Member.space_id == space_id, Member.user_id == user.id))
    if member is None:
        # 존재 여부를 숨기기 위해 404
        raise ApiError(404, "not_found")
    return SpaceAccess(space=space, role=member.role, user=user)


def space_reader(space_id: str, request: Request, db: Session = Depends(get_db)) -> SpaceAccess:
    """읽기 권한 (샘플 공간은 로그인 없이 읽기 가능)."""
    return get_space_access(db, space_id, _user_from_request(request, db))


def space_editor(space_id: str, request: Request, db: Session = Depends(get_db)) -> SpaceAccess:
    access = get_space_access(db, space_id, _user_from_request(request, db))
    access.require("editor")
    return access


def space_owner(space_id: str, request: Request, db: Session = Depends(get_db)) -> SpaceAccess:
    access = get_space_access(db, space_id, _user_from_request(request, db))
    access.require("owner")
    return access
