"""테스트 공통 설정.

- PostgreSQL 테스트 DB(YEOUN_TEST_DATABASE_URL, 기본 yeoun_test)를 쓴다.
- 세션 시작 때 alembic으로 스키마를 만들고, 테스트마다 모든 표를 비운다.
- AI 공급자는 모두 mock, 저장소는 임시 폴더(local).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="yeoun-test-"))

os.environ["YEOUN_ENV"] = "test"
os.environ["YEOUN_DATABASE_URL"] = os.environ.get(
    "YEOUN_TEST_DATABASE_URL", "postgresql+psycopg://yeoun:yeoun@localhost:5432/yeoun_test"
)
os.environ["YEOUN_DATA_DIR"] = str(_TMP)
os.environ["YEOUN_STORAGE"] = "local"
os.environ["YEOUN_MASTER_KEY"] = "dGVzdC1tYXN0ZXIta2V5LTMyLWJ5dGVzLWxvbmctISE="  # 테스트 전용
os.environ["YEOUN_WORKER_INLINE"] = "false"
for fn in ("STT", "LLM"):
    os.environ[f"YEOUN_{fn}_PROVIDER"] = "mock"
os.environ["YEOUN_DIARIZATION_PROVIDER"] = "mock"
os.environ["YEOUN_EMBEDDING_PROVIDER"] = "none"
os.environ["YEOUN_TOKENIZER"] = os.environ.get("YEOUN_TEST_TOKENIZER", "lite")
for k in list(os.environ):
    # 테스트가 실제 공급자를 부르지 않도록 키를 지운다
    if k.endswith("_API_KEY") and k.startswith("YEOUN_"):
        del os.environ[k]

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import reset_settings_cache  # noqa: E402
from app.db import Base, get_engine, new_session, reset_engine  # noqa: E402

SERVER_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    reset_settings_cache()
    reset_engine()
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    command.upgrade(cfg, "head")
    yield
    reset_engine()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_db():
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    objects = _TMP / "objects"
    if objects.exists():
        shutil.rmtree(objects)
    from app.routers import auth
    from app.search import index

    index._CACHE.clear()
    auth._attempts.clear()
    yield


@pytest.fixture
def db():
    s = new_session()
    try:
        yield s
    finally:
        s.close()


class ApiClient(TestClient):
    """CSRF 헤더를 자동으로 붙이는 테스트 클라이언트."""

    def request(self, method, url, **kwargs):  # type: ignore[override]
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("x-yeoun-request", "1")
        return super().request(method, url, headers=headers, **kwargs)


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    with ApiClient(app) as c:
        yield c


def make_client(app) -> ApiClient:
    return ApiClient(app)


def signup(
    client: TestClient, email: str = "a@example.com", password: str = "password123", name: str = "지은"
):
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def create_space(client: TestClient, name: str = "엄마", person: str = "엄마") -> dict:
    r = client.post("/api/spaces", json={"name": name, "person_name": person, "relationship": "어머니"})
    assert r.status_code == 201, r.text
    return r.json()
