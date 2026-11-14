"""DB 모델. 공간(space)을 지우면 ON DELETE CASCADE로 딸린 행이 모두 지워진다."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(40))
    prefs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    upload_bytes_total: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 토큰의 sha256
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(TS)
    last_seen_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    person_name: Mapped[str] = mapped_column(String(80))
    relationship: Mapped[str | None] = mapped_column(String(40), nullable=True)
    birthday: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    memorial_day: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # 공간별 데이터 키를 YEOUN_MASTER_KEY로 감싼 값 (봉투 암호화)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    index_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class Member(Base):
    __tablename__ = "members"

    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[dt.datetime] = mapped_column(TS)
    used_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # audio | video | photo
    source: Mapped[str] = mapped_column(String(10), default="upload")  # upload | ahead | sample
    origin: Mapped[str] = mapped_column(String(20), default="other")
    filename: Mapped[str] = mapped_column(String(255))
    ext: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    date_source: Mapped[str] = mapped_column(String(10), default="unknown")
    status: Mapped[str] = mapped_column(String(12), default="uploaded")
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    thumb_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    diarized: Mapped[bool] = mapped_column(Boolean, default=False)
    voice_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    link_id: Mapped[str | None] = mapped_column(
        ForeignKey("recording_links.id", ondelete="SET NULL"), nullable=True
    )
    question_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    question_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    caption: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sample_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    clips: Mapped[list[Clip]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", passive_deletes=True
    )
    speakers: Mapped[list[Speaker]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", passive_deletes=True
    )


class Speaker(Base):
    __tablename__ = "speakers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(10), default="unknown")  # person | other | unknown
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)

    asset: Mapped[Asset] = relationship(back_populates="speakers")


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    speaker_id: Mapped[str | None] = mapped_column(
        ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=0)
    start_sec: Mapped[float] = mapped_column(Float)
    end_sec: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text, default="")
    text_original: Mapped[str] = mapped_column(Text, default="")
    text_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    include_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    audio_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    audio_status: Mapped[str] = mapped_column(String(12), default="missing")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens: Mapped[list[str]] = mapped_column(JSONB, default=list)
    tokenizer: Mapped[str | None] = mapped_column(String(10), nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)

    asset: Mapped[Asset] = relationship(back_populates="clips")


class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    clip_id: Mapped[str] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="process_asset")
    status: Mapped[str] = mapped_column(
        String(10), default="queued", index=True
    )  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class StoredObject(Base):
    """저장소에 넣은 모든 파일 기록 (용량 계산·완전 삭제 확인용). 실제 바이트는 저장소 어댑터에 있다."""

    __tablename__ = "stored_objects"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class Blob(Base):
    """YEOUN_STORAGE=db일 때 암호화된 파일 바이트를 담는 표 (Render 무료 시연용)."""

    __tablename__ = "blobs"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class RecordingLink(Base):
    __tablename__ = "recording_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    sender_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(10), default="active")
    consent_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    expires_at: Mapped[dt.datetime] = mapped_column(TS)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class UsageCounter(Base):
    __tablename__ = "usage_counters"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    chats: Mapped[int] = mapped_column(Integer, default=0)


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(60))
    clip_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


class Book(Base):
    """목소리가 들리는 기억책 (공간마다 하나). 장·문단은 chapters JSON 하나로 둔다.

    chapters: [{id, title, period, paragraphs: [{id, text, clip_ids, grounded, edited}]}]
    문단의 clip_ids는 근거가 된 원본 클립이다. 클립이 지워지면 읽을 때 빠진다.
    """

    __tablename__ = "books"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_id: Mapped[str] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | approved
    chapters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    generated_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
    approved_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class NoticeDismissal(Base):
    """앱 안 알림을 닫은 기록 (같은 알림을 다시 띄우지 않기 위해)."""

    __tablename__ = "notice_dismissals"
    __table_args__ = (UniqueConstraint("user_id", "notice_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notice_id: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=utcnow)


Index("ix_clips_space_asset_seq", Clip.space_id, Clip.asset_id, Clip.seq)
