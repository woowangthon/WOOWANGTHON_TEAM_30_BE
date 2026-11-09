"""자료 올리기·목록·재시도·삭제."""

from __future__ import annotations

import hashlib
import logging
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AUDIO_EXTS, PHOTO_EXTS, VIDEO_EXTS, get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Asset, Space, User
from app.pipeline.dates import date_from_filename, guess_origin
from app.schemas import Asset as AssetOut
from app.schemas import AssetList, AssetUpdate
from app.security.auth import SpaceAccess, space_editor, space_reader
from app.services.assets import asset_out, clip_counts
from app.services.deletion import delete_asset_completely
from app.storage import blobstore
from app.worker import enqueue

router = APIRouter(tags=["assets"])
log = logging.getLogger("yeoun.assets")

CHUNK = 1024 * 1024


def kind_of(ext: str) -> str | None:
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in PHOTO_EXTS:
        return "photo"
    return None


def clean_filename(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name.strip() or "file"
    return "".join(ch for ch in base if ch.isprintable())[:200]


def read_limited(upload: UploadFile, limit: int) -> bytes:
    buf = bytearray()
    while True:
        chunk = upload.file.read(CHUNK)
        if not chunk:
            break
        buf += chunk
        if len(buf) > limit:
            raise ApiError(
                413, "file_too_large", f"파일 하나는 {limit // (1024 * 1024)}MB까지 올릴 수 있어요."
            )
    return bytes(buf)


def check_quotas(db: Session, space: Space, user: User | None, size: int) -> None:
    s = get_settings()
    quota = s.effective_space_quota_mb * 1024 * 1024
    # 원본 + 클립·미리보기(약 0.5배)를 함께 계산
    if quota and blobstore.space_usage(db, space.id) + int(size * 1.5) > quota:
        raise ApiError(
            413,
            "space_quota_exceeded",
            f"이 공간에는 {s.effective_space_quota_mb}MB까지 저장할 수 있어요. 쓰지 않는 자료를 지워 주세요.",
        )
    uq = s.effective_user_upload_quota_mb * 1024 * 1024
    if user is not None and uq and user.upload_bytes_total + size > uq:
        raise ApiError(413, "user_quota_exceeded")


def create_asset(
    db: Session,
    space: Space,
    *,
    data: bytes,
    filename: str,
    ext: str,
    kind: str,
    source: str,
    origin: str,
    uploaded_by: str | None,
    question_id: str | None = None,
    question_text: str | None = None,
    link_id: str | None = None,
) -> Asset:
    recorded = date_from_filename(filename)
    asset = Asset(
        space_id=space.id,
        kind=kind,
        source=source,
        origin=origin,
        filename=filename,
        ext=ext,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        recorded_at=recorded,
        date_source="filename" if recorded else "upload",
        status="uploaded",
        uploaded_by=uploaded_by,
        question_id=question_id,
        question_text=question_text,
        link_id=link_id,
        voice_reviewed=source != "upload",
    )
    db.add(asset)
    db.flush()
    key = blobstore.asset_prefix(space.id, asset.id) + "original"
    blobstore.save(db, space, key, data, asset_id=asset.id)
    asset.storage_key = key
    enqueue(db, asset)
    return asset


@router.post("/spaces/{space_id}/assets", response_model=AssetOut, status_code=201)
def upload(
    response: Response,
    file: UploadFile = File(...),
    consent: str = Form(""),
    origin: str | None = Form(None),
    access: SpaceAccess = Depends(space_editor),
    db: Session = Depends(get_db),
) -> AssetOut:
    s = get_settings()
    if consent.lower() not in ("true", "1", "yes", "on"):
        raise ApiError(400, "consent_required")
    filename = clean_filename(file.filename or "file")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = kind_of(ext)
    if kind is None:
        raise ApiError(
            415,
            "unsupported_file",
            "음성(m4a·mp3·wav·aac·amr·ogg), 영상(mp4·mov), 사진(jpg·png·heic)을 올릴 수 있어요.",
        )
    data = read_limited(file, s.max_file_mb * 1024 * 1024)
    if not data:
        raise ApiError(400, "empty_file")
    space = access.space
    # 같은 파일을 다시 올리면(네트워크 재시도 등) 기존 자료를 돌려준다
    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Asset).where(Asset.space_id == space.id, Asset.sha256 == digest).limit(1))
    if existing is not None:
        response.status_code = 200
        return asset_out(existing, clip_counts(db, [existing.id]).get(existing.id, 0))
    check_quotas(db, space, access.user, len(data))
    org = (
        origin if origin in ("call", "video", "voice_message", "other") else guess_origin(filename, kind, ext)
    )
    asset = create_asset(
        db,
        space,
        data=data,
        filename=filename,
        ext=ext,
        kind=kind,
        source="upload",
        origin=org,
        uploaded_by=access.user.id if access.user else None,
    )
    if access.user is not None:
        access.user.upload_bytes_total += len(data)
    db.commit()
    log.info("asset_uploaded asset=%s kind=%s size=%d", asset.id, kind, len(data))
    return asset_out(asset)


@router.get("/spaces/{space_id}/assets", response_model=AssetList)
def list_assets(access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)) -> AssetList:
    assets = db.scalars(
        select(Asset).where(Asset.space_id == access.space.id).order_by(Asset.created_at.desc())
    ).all()
    counts = clip_counts(db, [a.id for a in assets])
    return AssetList(assets=[asset_out(a, counts.get(a.id, 0)) for a in assets])


def _get_asset(db: Session, space_id: str, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.space_id != space_id:
        raise ApiError(404, "not_found")
    return asset


@router.get("/spaces/{space_id}/assets/{asset_id}", response_model=AssetOut)
def get_asset(
    asset_id: str, access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)
) -> AssetOut:
    asset = _get_asset(db, access.space.id, asset_id)
    return asset_out(asset, clip_counts(db, [asset.id]).get(asset.id, 0))


@router.patch("/spaces/{space_id}/assets/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: str,
    body: AssetUpdate,
    access: SpaceAccess = Depends(space_editor),
    db: Session = Depends(get_db),
) -> AssetOut:
    asset = _get_asset(db, access.space.id, asset_id)
    data = body.model_dump(exclude_unset=True)
    if "recorded_at" in data:
        asset.recorded_at = data["recorded_at"]
        asset.date_source = "user" if data["recorded_at"] else "unknown"
    if data.get("origin"):
        asset.origin = data["origin"]
    access.space.index_version += 1
    db.commit()
    return asset_out(asset, clip_counts(db, [asset.id]).get(asset.id, 0))


@router.post("/spaces/{space_id}/assets/{asset_id}/retry", response_model=AssetOut)
def retry(
    asset_id: str, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> AssetOut:
    asset = _get_asset(db, access.space.id, asset_id)
    if asset.status in ("queued", "processing", "uploaded"):
        raise ApiError(409, "processing_busy")
    enqueue(db, asset)
    db.commit()
    return asset_out(asset)


@router.delete("/spaces/{space_id}/assets/{asset_id}", status_code=204)
def delete_asset(
    asset_id: str, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> Response:
    asset = _get_asset(db, access.space.id, asset_id)
    delete_asset_completely(db, asset)
    db.commit()
    return Response(status_code=204)
