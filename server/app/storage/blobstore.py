"""암호화 저장 + 용량 기록. 모든 파일은 이 모듈을 거쳐 저장한다."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Space, StoredObject
from app.security import crypto
from app.storage import get_storage


def space_prefix(space_id: str) -> str:
    return f"spaces/{space_id}/"


def asset_prefix(space_id: str, asset_id: str) -> str:
    return f"spaces/{space_id}/assets/{asset_id}/"


def data_key(space: Space) -> bytes:
    return crypto.unwrap_key(space.wrapped_key, space.id)


def save(db: Session, space: Space, key: str, plaintext: bytes, asset_id: str | None = None) -> int:
    """암호화해서 저장하고 stored_objects에 기록한다. 저장된(암호문) 크기를 돌려준다."""
    assert key.startswith(space_prefix(space.id)), "다른 공간 경로에 저장할 수 없습니다"
    blob = crypto.encrypt_bytes(data_key(space), plaintext, aad=key)
    get_storage().put(key, blob)
    existing = db.get(StoredObject, key)
    if existing:
        existing.size = len(blob)
    else:
        db.add(StoredObject(key=key, space_id=space.id, asset_id=asset_id, size=len(blob)))
    db.flush()
    return len(blob)


def load(space: Space, key: str) -> bytes:
    blob = get_storage().get(key)
    return crypto.decrypt_bytes(data_key(space), blob, aad=key)


def remove(db: Session, key: str) -> None:
    get_storage().delete(key)
    db.execute(delete(StoredObject).where(StoredObject.key == key))


def remove_asset_files(db: Session, space_id: str, asset_id: str) -> int:
    n = get_storage().delete_prefix(asset_prefix(space_id, asset_id))
    db.execute(delete(StoredObject).where(StoredObject.asset_id == asset_id))
    return n


def remove_space_files(db: Session, space_id: str) -> int:
    n = get_storage().delete_prefix(space_prefix(space_id))
    db.execute(delete(StoredObject).where(StoredObject.space_id == space_id))
    return n


def space_usage(db: Session, space_id: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(StoredObject.size), 0)).where(StoredObject.space_id == space_id)
        )
        or 0
    )
