"""보안·삭제·내보내기·권한·로그 테스트."""

from __future__ import annotations

import io
import json
import logging
import zipfile

import pytest

from app.config import FIXTURES_DIR, get_settings
from app.worker import run_pending_jobs
from tests.conftest import ApiClient, create_space, signup
from tests.helpers import ready_space
from tests.test_pipeline import FIXTURE, upload


def _objects_root():
    return get_settings().data_dir / "objects"


def test_delete_space_removes_everything(client, db):
    from app.models import Asset, Clip, Favorite, Job, RecordingLink, Speaker, StoredObject
    from app.search import index

    space, clips = ready_space(client)
    sid = space["id"]
    client.put(f"/api/spaces/{sid}/clips/{clips[1]['id']}/favorite", json={"favorite": True})
    client.post(f"/api/spaces/{sid}/links", json={"question_ids": ["q001"]})
    client.post(f"/api/spaces/{sid}/chat", json={"message": "밥"})  # 색인 캐시 생성
    assert sid in index._CACHE
    space_dir = _objects_root() / "spaces" / sid
    assert any(space_dir.rglob("*"))

    r = client.post(f"/api/spaces/{sid}/delete", json={"confirm_name": space["name"]})
    assert r.status_code == 204
    assert not space_dir.exists() or not any(p.is_file() for p in space_dir.rglob("*"))
    for model in (Asset, Clip, Speaker, Job, StoredObject, RecordingLink, Favorite):
        assert db.query(model).count() == 0, model.__name__
    assert sid not in index._CACHE
    assert client.get(f"/api/spaces/{sid}").status_code == 404


def test_delete_asset_removes_only_its_files(client, db, tmp_path):
    from app.models import Clip, StoredObject
    from app.pipeline.media import make_test_tone

    signup(client)
    space = create_space(client)
    sid = space["id"]
    a = upload(client, sid).json()
    other = tmp_path / "other.wav"
    make_test_tone(other, seconds=5)
    b = upload(client, sid, path=other).json()
    run_pending_jobs()
    assert client.delete(f"/api/spaces/{sid}/assets/{a['id']}").status_code == 204
    assert not (_objects_root() / "spaces" / sid / "assets" / a["id"]).exists()
    assert any((_objects_root() / "spaces" / sid / "assets" / b["id"]).rglob("*"))
    assert db.query(Clip).filter_by(asset_id=a["id"]).count() == 0
    assert db.query(StoredObject).filter_by(asset_id=a["id"]).count() == 0
    assert db.query(StoredObject).filter_by(asset_id=b["id"]).count() > 0


def test_account_deletion_removes_owned_spaces(client, db):
    from app.models import Space, StoredObject, User

    ready_space(client)
    r = client.post("/api/me/delete", json={"password": "wrong-password"})
    assert r.status_code == 401
    r = client.post("/api/me/delete", json={"password": "password123"})
    assert r.status_code == 204
    assert db.query(User).count() == 0
    assert db.query(Space).count() == 0
    assert db.query(StoredObject).count() == 0
    assert not any(p.is_file() for p in _objects_root().rglob("*"))


def test_db_storage_backend_and_deletion(app, db, monkeypatch):
    from app.models import Blob
    from app.storage import reset_storage

    monkeypatch.setattr(get_settings(), "storage", "db")
    reset_storage()
    try:
        c = ApiClient(app)
        space, clips = ready_space(c)
        assert db.query(Blob).count() == 6
        blob = db.query(Blob).first()
        assert blob.data.startswith(b"YE1")
        media = c.get(clips[1]["audio_url"])
        assert media.status_code == 200 and media.headers["content-type"] == "audio/mpeg"
        c.post(f"/api/spaces/{space['id']}/delete", json={"confirm_name": space["name"]})
        db.expire_all()
        assert db.query(Blob).count() == 0
    finally:
        monkeypatch.setattr(get_settings(), "storage", "local")
        reset_storage()


def test_encryption_binds_key_and_location():
    from cryptography.exceptions import InvalidTag

    from app.security import crypto

    k1, k2 = crypto.new_data_key(), crypto.new_data_key()
    blob = crypto.encrypt_bytes(k1, b"secret voice", aad="spaces/a/assets/x/original")
    assert crypto.decrypt_bytes(k1, blob, aad="spaces/a/assets/x/original") == b"secret voice"
    with pytest.raises(InvalidTag):
        crypto.decrypt_bytes(k2, blob, aad="spaces/a/assets/x/original")  # 다른 공간 키
    with pytest.raises(InvalidTag):
        crypto.decrypt_bytes(k1, blob, aad="spaces/b/assets/y/original")  # 다른 위치로 옮긴 파일
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(InvalidTag):
        crypto.decrypt_bytes(k1, tampered, aad="spaces/a/assets/x/original")
    wrapped = crypto.wrap_key(k1, "space-1")
    assert crypto.unwrap_key(wrapped, "space-1") == k1
    with pytest.raises(InvalidTag):
        crypto.unwrap_key(wrapped, "space-2")


def test_master_key_required_outside_dev(monkeypatch):
    from app.security import crypto

    s = get_settings()
    monkeypatch.setattr(s, "env", "production")
    monkeypatch.setattr(s, "master_key", None)
    crypto.reset_key_cache()
    try:
        with pytest.raises(crypto.MasterKeyMissing):
            crypto.master_key()
    finally:
        crypto.reset_key_cache()


def test_export_zip(client):
    space, clips = ready_space(client)
    r = client.get(f"/api/spaces/{space['id']}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "자막.json" in names
    original = [n for n in names if n.startswith("원본/")]
    assert len(original) == 1
    assert z.read(original[0]) == FIXTURE.read_bytes()  # 암호를 푼 원본 그대로
    data = json.loads(z.read("자막.json"))
    assert len(data["clips"]) == 5
    assert {c["speaker_role"] for c in data["clips"]} == {"person", "other"}


def test_permissions_matrix(app, db):
    from app.models import Member, User

    owner = ApiClient(app)
    space, clips = ready_space(owner)
    sid = space["id"]
    stranger, viewer, editor = ApiClient(app), ApiClient(app), ApiClient(app)
    signup(stranger, "s@example.com")
    signup(viewer, "v@example.com")
    signup(editor, "e@example.com")
    for email, role in (("v@example.com", "viewer"), ("e@example.com", "editor")):
        u = db.query(User).filter_by(email=email).one()
        db.add(Member(space_id=sid, user_id=u.id, role=role))
    db.commit()
    cid = clips[1]["id"]

    reads = [
        ("get", f"/api/spaces/{sid}", None),
        ("get", f"/api/spaces/{sid}/assets", None),
        ("get", f"/api/spaces/{sid}/voices", None),
        ("get", f"/api/spaces/{sid}/timeline", None),
        ("post", f"/api/spaces/{sid}/chat", {"message": "밥"}),
        ("get", f"/api/spaces/{sid}/providers", None),
        ("get", f"/api/spaces/{sid}/members", None),
    ]
    writes = [
        ("patch", f"/api/spaces/{sid}/clips/{cid}", {"text": "바꿈"}),
        ("post", f"/api/spaces/{sid}/links", {"question_ids": ["q001"]}),
        ("patch", f"/api/spaces/{sid}", {"note": "x"}),
    ]
    owner_only = [
        ("get", f"/api/spaces/{sid}/export", None),
        ("post", f"/api/spaces/{sid}/invites", {"role": "viewer"}),
        ("post", f"/api/spaces/{sid}/delete", {"confirm_name": space["name"]}),
    ]

    def call(c, method, url, body):
        return getattr(c, method)(url, json=body) if body is not None else getattr(c, method)(url)

    for method, url, body in reads + writes + owner_only:
        assert call(stranger, method, url, body).status_code == 404, url
    for method, url, body in reads:
        assert call(viewer, method, url, body).status_code == 200, url
    for method, url, body in writes + owner_only:
        assert call(viewer, method, url, body).status_code == 403, url
    for method, url, body in writes:
        assert call(editor, method, url, body).status_code in (200, 201), url
    for method, url, body in owner_only:
        assert call(editor, method, url, body).status_code == 403, url
    # 다른 공간의 클립 ID로 우회할 수 없다
    other_space = create_space(stranger, "아빠")
    r = stranger.patch(f"/api/spaces/{other_space['id']}/clips/{cid}", json={"text": "x"})
    assert r.status_code == 404
    r = stranger.put(f"/api/spaces/{other_space['id']}/clips/{cid}/favorite", json={"favorite": True})
    assert r.status_code == 404


def test_family_invite_flow(app):
    owner = ApiClient(app)
    space, _ = ready_space(owner)
    sid = space["id"]
    inv = owner.post(f"/api/spaces/{sid}/invites", json={"role": "viewer"}).json()
    token = inv["url"].rsplit("/", 1)[-1]
    family = ApiClient(app)
    preview = family.get(f"/api/invites/{token}").json()
    assert preview["space_name"] == "엄마" and preview["role"] == "viewer"
    assert family.post(f"/api/invites/{token}/accept").status_code == 401
    signup(family, "f@example.com", name="오빠")
    assert family.post(f"/api/invites/{token}/accept").json() == {"space_id": sid}
    assert family.get(f"/api/spaces/{sid}").json()["role"] == "viewer"
    members = owner.get(f"/api/spaces/{sid}/members").json()["members"]
    assert [m["role"] for m in members] == ["owner", "viewer"]
    # 1회용
    third = ApiClient(app)
    signup(third, "t@example.com")
    assert third.post(f"/api/invites/{token}/accept").status_code == 410
    # 권한 바꾸기·내보내기
    fid = members[1]["user_id"]
    assert owner.patch(f"/api/spaces/{sid}/members/{fid}", json={"role": "editor"}).json()["role"] == "editor"
    assert owner.delete(f"/api/spaces/{sid}/members/{fid}").status_code == 204
    assert family.get(f"/api/spaces/{sid}").status_code == 404


def test_logs_do_not_contain_transcripts_or_filenames(client, caplog):
    caplog.set_level(logging.DEBUG)
    space, clips = ready_space(client)
    client.post(f"/api/spaces/{space['id']}/chat", json={"message": "비밀스러운 우리 집 김장 이야기"})
    link = client.post(f"/api/spaces/{space['id']}/links", json={"question_ids": ["q001"]}).json()
    token = link["url"].rsplit("/", 1)[-1]
    client.get(f"/api/record/{token}")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "통화 녹음 엄마" not in text
    assert "비밀스러운" not in text
    for c in clips:
        if c["text"]:
            assert c["text"][:12] not in text
    assert token not in text


def test_redact_filter():
    from app.logging_setup import redact

    assert "abc123secrettoken" not in redact("GET /api/record/abc123secrettoken HTTP/1.1")
    assert "sk-proj-abcdef1234567890" not in redact("key sk-proj-abcdef1234567890")
    assert "s3cr3t" not in redact('{"password": "s3cr3t"}')


def test_provider_policy(monkeypatch):
    from pydantic import SecretStr

    from app.ai import registry

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "auto")
    monkeypatch.setattr(s, "gemini_api_key", SecretStr("test-key"))
    monkeypatch.setattr(s, "gemini_tier", "free")
    monkeypatch.setattr(s, "env", "production")
    res = registry.resolve("llm", consent=True)
    assert res.name == "mock" and ("gemini", "blocked_by_policy") in res.blocked
    assert registry.resolve("llm", is_sample=True).name == "gemini"  # 가상 샘플은 허용
    monkeypatch.setattr(s, "env", "staging")
    assert registry.resolve("llm", consent=False).name == "mock"
    assert registry.resolve("llm", consent=True).name == "gemini"
    monkeypatch.setattr(s, "gemini_tier", "paid")
    monkeypatch.setattr(s, "env", "production")
    assert registry.resolve("llm", consent=False).name == "gemini"
    monkeypatch.setattr(s, "anthropic_api_key", SecretStr("test-key-2"))
    assert registry.resolve("llm").name == "anthropic"


def test_only_yeoun_prefixed_env_is_read(monkeypatch):
    from app.ai.base import api_key
    from app.config import Settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-be-read")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-be-read")
    s = Settings()
    assert s.anthropic_api_key is None and s.openai_api_key is None
    assert api_key("anthropic") is None


def test_providers_endpoint(client):
    space, _ = ready_space(client)
    r = client.get(f"/api/spaces/{space['id']}/providers").json()
    fns = {p["function"] for p in r["providers"]}
    assert fns == {"stt", "diarization", "llm", "embedding"}
    assert any("암호화" in x for x in r["retention"])
    assert all(p["is_external"] is False for p in r["providers"])  # 테스트는 mock


def test_sample_fixture_is_fictional():
    data = json.loads((FIXTURES_DIR / "demo" / "sample-space.json").read_text(encoding="utf-8"))
    assert data["space"]["name"].startswith("[샘플]")
