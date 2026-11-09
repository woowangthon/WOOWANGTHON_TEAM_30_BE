"""저장소 어댑터.

- local: 개발용, YEOUN_DATA_DIR/objects 아래 파일
- db:    Render 무료 시연용, PostgreSQL blobs 표 (용량 제한 필수)
- s3:    실사용용, S3 호환 저장소 (Cloudflare R2 등)

어댑터는 이미 암호화된 바이트만 다룬다. 암호화·용량 기록은 app.storage.blobstore가 맡는다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Storage(Protocol):
    name: str

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def list_prefix(self, prefix: str) -> list[str]: ...


class StorageNotFound(KeyError):
    pass


def _safe_key(key: str) -> str:
    if key.startswith("/") or ".." in key.split("/") or "\\" in key:
        raise ValueError("잘못된 저장소 키")
    return key


class LocalStorage:
    name = "local"

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise StorageNotFound(key)
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def list_prefix(self, prefix: str) -> list[str]:
        base = self.root / _safe_key(prefix) if prefix else self.root
        if base.is_file():
            return [prefix]
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    def delete_prefix(self, prefix: str) -> int:
        keys = self.list_prefix(prefix)
        for k in keys:
            self.delete(k)
        # 빈 디렉터리 정리
        base = self.root / _safe_key(prefix)
        if base.is_dir():
            for d in sorted((p for p in base.rglob("*") if p.is_dir()), reverse=True):
                try:
                    d.rmdir()
                except OSError:
                    pass
            try:
                base.rmdir()
            except OSError:
                pass
        return len(keys)


class DbStorage:
    """PostgreSQL blobs 표에 저장. 요청 트랜잭션과 분리된 짧은 트랜잭션을 쓴다."""

    name = "db"

    def put(self, key: str, data: bytes) -> None:
        from sqlalchemy.dialects.postgresql import insert

        from app.db import get_engine
        from app.models import Blob

        stmt = insert(Blob).values(key=_safe_key(key), data=data, size=len(data))
        stmt = stmt.on_conflict_do_update(index_elements=[Blob.key], set_={"data": data, "size": len(data)})
        with get_engine().begin() as conn:
            conn.execute(stmt)

    def get(self, key: str) -> bytes:
        from sqlalchemy import select

        from app.db import get_engine
        from app.models import Blob

        with get_engine().connect() as conn:
            row = conn.execute(select(Blob.data).where(Blob.key == key)).first()
        if row is None:
            raise StorageNotFound(key)
        return bytes(row[0])

    def exists(self, key: str) -> bool:
        from sqlalchemy import select

        from app.db import get_engine
        from app.models import Blob

        with get_engine().connect() as conn:
            return conn.execute(select(Blob.key).where(Blob.key == key)).first() is not None

    def delete(self, key: str) -> None:
        from sqlalchemy import delete

        from app.db import get_engine
        from app.models import Blob

        with get_engine().begin() as conn:
            conn.execute(delete(Blob).where(Blob.key == key))

    def list_prefix(self, prefix: str) -> list[str]:
        from sqlalchemy import select

        from app.db import get_engine
        from app.models import Blob

        with get_engine().connect() as conn:
            rows = conn.execute(select(Blob.key).where(Blob.key.startswith(prefix, autoescape=True))).all()
        return sorted(r[0] for r in rows)

    def delete_prefix(self, prefix: str) -> int:
        from sqlalchemy import delete

        from app.db import get_engine
        from app.models import Blob

        with get_engine().begin() as conn:
            res = conn.execute(delete(Blob).where(Blob.key.startswith(prefix, autoescape=True)))
        return int(res.rowcount or 0)


class S3Storage:
    name = "s3"

    def __init__(self) -> None:
        import boto3  # 무거운 모듈이라 s3를 쓸 때만 불러온다

        s = get_settings()
        if not s.s3_bucket:
            raise RuntimeError("YEOUN_S3_BUCKET이 필요합니다")
        self.bucket = s.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key_id.get_secret_value() if s.s3_access_key_id else None,
            aws_secret_access_key=s.s3_secret_access_key.get_secret_value()
            if s.s3_secret_access_key
            else None,
        )

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=_safe_key(key), Body=data)

    def get(self, key: str) -> bytes:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey as e:
            raise StorageNotFound(key) from e
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def list_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return sorted(keys)

    def delete_prefix(self, prefix: str) -> int:
        keys = self.list_prefix(prefix)
        for i in range(0, len(keys), 1000):
            chunk = keys[i : i + 1000]
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in chunk]})
        return len(keys)


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage == "db":
        return DbStorage()
    if s.storage == "s3":
        return S3Storage()
    return LocalStorage(s.data_dir / "objects")


def reset_storage() -> None:
    get_storage.cache_clear()
