"""설정. 환경 변수는 YEOUN_ 접두사만 읽는다 (ANTHROPIC_API_KEY 같은 공급자 기본 변수는 읽지 않는다)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_DIR = REPO_ROOT / "shared"
FIXTURES_DIR = REPO_ROOT / "fixtures"

Env = Literal["development", "staging", "production", "test"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YEOUN_", env_file=None, extra="ignore")

    env: Env = "development"
    version: str = "0.1.0"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://yeoun:yeoun@localhost:5432/yeoun"

    # 비밀 값 — 로그·응답에 절대 내보내지 않는다
    master_key: SecretStr | None = None
    session_secret: SecretStr | None = None

    # 저장소
    storage: Literal["local", "db", "s3"] = "local"
    data_dir: Path = REPO_ROOT / ".data"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    # 작업 처리: true면 API 프로세스 안의 스레드가 처리 (Render 무료 등급)
    worker_inline: bool = True
    worker_poll_sec: float = 1.0

    # 링크(녹음·초대)에 쓰는 웹 주소. 비워 두면 요청의 Origin(웹 주소)을 쓴다.
    public_web_url: str = ""

    # 친구 테스트(staging) 제한
    invite_codes: str = ""
    max_file_mb: int = 25
    space_quota_mb: int | None = None  # None이면 저장소에 따라 자동 (db: 150MB, 그 외: 제한 없음)
    user_upload_quota_mb: int | None = None  # None이면 staging 300MB, 그 외 제한 없음
    chat_daily_limit: int | None = None  # None이면 staging 150회, 그 외 제한 없음
    sample_chat_per_minute: int = 20
    max_audio_minutes: int = 90
    max_photo_pixels: int = 60_000_000

    # 검색
    tokenizer: Literal["auto", "kiwi", "lite"] = "auto"
    match_threshold: float = 0.34

    # AI 공급자 (auto = 키가 있으면 실제 공급자, 없으면 mock/none)
    stt_provider: Literal["auto", "mock", "openai", "gemini"] = "auto"
    diarization_provider: Literal["auto", "none", "mock", "openai"] = "auto"
    llm_provider: Literal["auto", "mock", "anthropic", "openai", "gemini", "replay"] = "auto"
    embedding_provider: Literal["auto", "none", "openai", "gemini"] = "auto"

    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    gemini_tier: Literal["free", "paid"] = "free"

    anthropic_model: str = "claude-haiku-5-5"
    openai_llm_model: str = "gpt-5-mini"
    openai_stt_model: str = "whisper-1"
    openai_diarize_model: str = "gpt-4o-transcribe-diarize"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    llm_timeout_sec: float = 20.0
    stt_timeout_sec: float = 300.0

    llm_replay_path: Path = FIXTURES_DIR / "llm-replay" / "default.json"
    care_llm_classifier: bool = True

    # 세션·링크
    session_days: int = 30
    media_url_ttl_sec: int = 900
    recording_max_seconds: int = 300
    cookie_secure: bool | None = None

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Render는 postgres:// 또는 postgresql:// 형태를 준다 → psycopg3 드라이버로 맞춘다
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    # ---- 파생 값
    @property
    def is_dev_like(self) -> bool:
        return self.env in ("development", "test")

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return not self.is_dev_like

    @property
    def invite_code_set(self) -> set[str]:
        return {c.strip() for c in self.invite_codes.split(",") if c.strip()}

    @property
    def signup_requires_invite(self) -> bool:
        return self.env == "staging" or bool(self.invite_code_set)

    @property
    def effective_space_quota_mb(self) -> int:
        if self.space_quota_mb is not None:
            return self.space_quota_mb
        return 150 if self.storage == "db" else 0

    @property
    def effective_user_upload_quota_mb(self) -> int:
        if self.user_upload_quota_mb is not None:
            return self.user_upload_quota_mb
        return 300 if self.env == "staging" else 0

    @property
    def effective_chat_daily_limit(self) -> int:
        if self.chat_daily_limit is not None:
            return self.chat_daily_limit
        return 150 if self.env == "staging" else 0


AUDIO_EXTS = {"m4a", "mp3", "wav", "aac", "amr", "ogg", "opus", "webm", "3gp"}
VIDEO_EXTS = {"mp4", "mov", "m4v", "3gp2"}
PHOTO_EXTS = {"jpg", "jpeg", "png", "heic", "heif"}
# 사용자에게 안내하는 확장자 목록 (webm·opus·3gp는 녹음기/일부 기종용으로 함께 받는다)
ALLOWED_EXTS = sorted(AUDIO_EXTS | VIDEO_EXTS | PHOTO_EXTS)


def web_base_url(origin_header: str | None) -> str:
    """녹음·초대 링크의 앞부분. 설정값 → 브라우저 Origin → 개발 기본값 순서."""
    s = get_settings()
    if s.public_web_url.strip():
        return s.public_web_url.strip().rstrip("/")
    if origin_header and origin_header.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        return origin_header.rstrip("/")
    return "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
