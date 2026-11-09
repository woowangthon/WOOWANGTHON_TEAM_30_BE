from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai import registry
from app.config import ALLOWED_EXTS, get_settings
from app.db import get_db
from app.models import Space
from app.schemas import AppConfig, AppLimits, Health

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=Health)
def health(db: Session = Depends(get_db)) -> Health:
    ok = True
    try:
        db.execute(text("select 1"))
    except Exception:
        ok = False
    return Health(ok=ok, version=get_settings().version, db=ok)


@router.get("/config", response_model=AppConfig)
def app_config(db: Session = Depends(get_db)) -> AppConfig:
    s = get_settings()
    sample_id = db.scalar(select(Space.id).where(Space.is_sample.is_(True)).limit(1))
    return AppConfig(
        env=s.env,
        signup_requires_invite=s.signup_requires_invite,
        sample_space_id=sample_id,
        limits=AppLimits(
            max_file_mb=s.max_file_mb,
            space_quota_mb=s.effective_space_quota_mb,
            user_upload_quota_mb=s.effective_user_upload_quota_mb,
            chat_daily_limit=s.effective_chat_daily_limit,
            allowed_extensions=ALLOWED_EXTS,
        ),
        stt_available=registry.live_stt_available(),
    )
