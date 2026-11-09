from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Space, User
from app.schemas import DeleteAccountRequest, LoginRequest, SignupRequest, UserPrefs, UserPrefsUpdate
from app.schemas import User as UserOut
from app.security.auth import (
    COOKIE_NAME,
    burn_verify_time,
    clear_session,
    create_session,
    current_user,
    hash_password,
    verify_password,
)

router = APIRouter(tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_PREFS = UserPrefs(
    large_text=False, rest_reminder=True, rest_minutes=40, consent_training_providers=False
)

# 간단한 로그인 시도 제한 (IP+이메일 기준, 10분에 10회)
_attempts: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(key: str, limit: int = 10, window: float = 600) -> None:
    now = time.monotonic()
    q = _attempts[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise ApiError(429, "rate_limited")
    q.append(now)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def user_prefs(user: User) -> UserPrefs:
    data = DEFAULT_PREFS.model_dump()
    data.update({k: v for k, v in (user.prefs or {}).items() if k in data and v is not None})
    return UserPrefs(**data)


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        prefs=user_prefs(user),
        created_at=user.created_at,
    )


@router.post("/auth/signup", response_model=UserOut, status_code=201)
def signup(
    body: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    s = get_settings()
    _rate_limit(f"signup:{client_ip(request)}", limit=20, window=3600)
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ApiError(400, "invalid_email")
    if len(body.password) < 8:
        raise ApiError(400, "weak_password")
    if s.signup_requires_invite:
        code = (body.invite_code or "").strip()
        if not code:
            raise ApiError(403, "invite_required")
        if code not in s.invite_code_set:
            raise ApiError(403, "invalid_invite")
    if db.scalar(select(func.count()).select_from(User).where(User.email == email)):
        raise ApiError(409, "email_taken")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
        prefs=DEFAULT_PREFS.model_dump(),
    )
    db.add(user)
    db.flush()
    create_session(db, user, response)
    db.commit()
    return user_out(user)


@router.post("/auth/login", response_model=UserOut)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> UserOut:
    email = body.email.strip().lower()
    _rate_limit(f"login:{client_ip(request)}:{email}")
    user = db.scalar(select(User).where(User.email == email, User.is_system.is_(False)))
    if user is None:
        burn_verify_time(body.password)
        raise ApiError(401, "invalid_credentials")
    if not verify_password(user.password_hash, body.password):
        raise ApiError(401, "invalid_credentials")
    create_session(db, user, response)
    db.commit()
    return user_out(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    clear_session(db, request, response)
    db.commit()
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return user_out(user)


@router.patch("/me/prefs", response_model=UserOut)
def update_prefs(
    body: UserPrefsUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> UserOut:
    prefs = user_prefs(user).model_dump()
    for k, v in body.model_dump(exclude_none=True).items():
        prefs[k] = v
    user.prefs = UserPrefs(**prefs).model_dump()
    db.add(user)
    db.commit()
    return user_out(user)


@router.post("/me/delete", status_code=204)
def delete_account(
    body: DeleteAccountRequest,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """계정 삭제: 내가 소유한 공간(파일·자막·색인·작업 기록)까지 모두 지운다."""
    from app.services.deletion import delete_space_completely

    if not verify_password(user.password_hash, body.password):
        raise ApiError(401, "invalid_credentials")
    owned = db.scalars(select(Space).where(Space.owner_id == user.id)).all()
    for space in owned:
        delete_space_completely(db, space)
    # 세션 행은 사용자 삭제와 함께 FK CASCADE로 지워진다
    response.delete_cookie(COOKIE_NAME, path="/")
    db.delete(user)
    db.commit()
    response.status_code = 204
    return response
