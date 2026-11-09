from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.config import FIXTURES_DIR
from app.worker import run_pending_jobs
from tests.conftest import ApiClient, create_space, signup

FIXTURE = FIXTURES_DIR / "upload" / "통화 녹음 엄마_240315_190000.m4a"


def upload(client, space_id: str, path: Path = FIXTURE, consent: str = "true", name: str | None = None):
    with path.open("rb") as f:
        return client.post(
            f"/api/spaces/{space_id}/assets",
            files={"file": (name or path.name, f, "audio/mp4")},
            data={"consent": consent},
        )


def processed_space(client) -> tuple[dict, dict]:
    signup(client)
    space = create_space(client)
    r = upload(client, space["id"])
    assert r.status_code == 201, r.text
    assert run_pending_jobs() == 1
    asset = client.get(f"/api/spaces/{space['id']}/assets/{r.json()['id']}").json()
    return space, asset


def test_upload_requires_consent(client):
    signup(client)
    space = create_space(client)
    r = upload(client, space["id"], consent="")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "consent_required"


def test_upload_rejects_unknown_type(client, tmp_path):
    signup(client)
    space = create_space(client)
    p = tmp_path / "notes.txt"
    p.write_text("hello")
    r = upload(client, space["id"], path=p)
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "unsupported_file"


def test_full_pipeline_with_mock_providers(client, db):
    from app.models import Clip, Speaker

    space, asset = processed_space(client)
    assert asset["status"] == "ready", asset
    assert [s["state"] for s in asset["stages"]] == ["done"] * 6
    assert asset["recorded_at"] == "2024-03-15"  # 파일명에서
    assert asset["date_source"] == "filename"
    assert asset["origin"] == "call"
    assert asset["duration_sec"] > 25
    assert asset["clip_count"] == 5

    clips = db.query(Clip).order_by(Clip.seq).all()
    assert all(2.0 <= c.end_sec - c.start_sec <= 30.0 for c in clips)
    assert clips[1].text.startswith("그래, 고생 많았다")
    assert all(c.audio_status == "ready" for c in clips)
    assert all(c.tokens for c in clips)
    # 정해진 태그 목록 안에서만
    from app.schemas import TAG_VALUES

    assert all(set(c.tags) <= set(TAG_VALUES) for c in clips)
    assert "음식" in clips[3].tags
    speakers = db.query(Speaker).all()
    assert len(speakers) == 2
    assert all(s.role == "unknown" for s in speakers)  # 사용자가 목소리 확인에서 고른다

    sp = client.get(f"/api/spaces/{space['id']}").json()
    assert sp["counts"]["clips"] == 5
    assert sp["counts"]["person_clips"] == 0
    assert sp["counts"]["pending_voice"] == 1


def test_files_are_encrypted_at_rest(client, db):
    from app.config import get_settings
    from app.models import StoredObject

    processed_space(client)
    root = get_settings().data_dir / "objects"
    original_bytes = FIXTURE.read_bytes()
    objects = db.query(StoredObject).all()
    assert len(objects) == 6  # 원본 1 + 클립 5
    for obj in objects:
        raw = (root / obj.key).read_bytes()
        assert raw.startswith(b"YE1")
        assert b"ftyp" not in raw[:64]  # m4a 머리가 보이면 안 된다
        assert b"ID3" not in raw[:16] and b"\xff\xfb" not in raw[:16]
        assert original_bytes[:1000] not in raw


def test_same_file_twice_returns_existing(client):
    signup(client)
    space = create_space(client)
    a = upload(client, space["id"])
    b = upload(client, space["id"])
    assert a.status_code == 201
    assert b.status_code == 200
    assert a.json()["id"] == b.json()["id"]


def test_unknown_audio_without_fixture_gets_empty_captions(client, db, tmp_path):
    """키도 fixture도 없으면 말소리 구간만 나누고 자막은 비워 둔다 (지어내지 않는다)."""
    from app.models import Clip
    from app.pipeline.media import make_test_tone

    signup(client)
    space = create_space(client)
    p = tmp_path / "voice_20230101.wav"
    make_test_tone(p, seconds=7)
    assert upload(client, space["id"], path=p).status_code == 201
    run_pending_jobs()
    asset = client.get(f"/api/spaces/{space['id']}/assets").json()["assets"][0]
    assert asset["status"] == "ready"
    stt_stage = next(s for s in asset["stages"] if s["name"] == "stt")
    assert "자막" in (stt_stage["note"] or "")
    clips = db.query(Clip).all()
    assert clips and all(c.text == "" for c in clips)


def test_broken_file_fails_with_korean_message_and_retry(client, tmp_path):
    signup(client)
    space = create_space(client)
    p = tmp_path / "broken.m4a"
    p.write_bytes(b"this is not audio" * 100)
    r = upload(client, space["id"], path=p)
    assert r.status_code == 201
    run_pending_jobs()
    asset = client.get(f"/api/spaces/{space['id']}/assets/{r.json()['id']}").json()
    assert asset["status"] == "failed"
    assert asset["error"]["code"] == "unreadable_media"
    assert "파일" in asset["error"]["message_ko"]
    rr = client.post(f"/api/spaces/{space['id']}/assets/{asset['id']}/retry")
    assert rr.status_code == 200
    assert rr.json()["status"] == "queued"


def test_photo_exif_date_and_thumbnail(client, db, tmp_path):
    signup(client)
    space = create_space(client)
    img = Image.new("RGB", (2000, 1500), (200, 150, 120))
    exif = Image.Exif()
    exif[306] = "2019:02:04 09:30:00"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    p = tmp_path / "IMG_0001.jpg"
    p.write_bytes(buf.getvalue())
    r = upload(client, space["id"], path=p)
    assert r.status_code == 201
    run_pending_jobs()
    asset = client.get(f"/api/spaces/{space['id']}/assets/{r.json()['id']}").json()
    assert asset["status"] == "ready"
    assert asset["recorded_at"] == "2019-02-04"
    assert asset["date_source"] == "exif"
    thumb = client.get(asset["thumb_url"])
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(thumb.content)).size) == 1280


def test_space_quota(app, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "space_quota_mb", 0)
    c = ApiClient(app)
    signup(c)
    space = create_space(c)
    monkeypatch.setattr(get_settings(), "space_quota_mb", 1)  # 1MB
    big = FIXTURES_DIR.parent / "server" / "tests" / "_big.wav"
    try:
        from app.pipeline.media import make_test_tone

        make_test_tone(big, seconds=40)  # 약 1.3MB
        r = upload(c, space["id"], path=big)
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "space_quota_exceeded"
    finally:
        big.unlink(missing_ok=True)


def test_file_size_limit(app, monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_file_mb", 1)
    c = ApiClient(app)
    signup(c)
    space = create_space(c)
    p = tmp_path / "big.mp3"
    p.write_bytes(b"\0" * (1024 * 1024 + 10))
    r = upload(c, space["id"], path=p)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "file_too_large"


def test_viewer_cannot_upload_and_other_user_cannot_see(app):
    a = ApiClient(app)
    b = ApiClient(app)
    signup(a, "a@example.com")
    signup(b, "b@example.com")
    space = create_space(a)
    r = upload(b, space["id"])
    assert r.status_code == 404
    assert b.get(f"/api/spaces/{space['id']}/assets").status_code == 404


def test_signed_media_url_expires_and_is_tamper_proof(client, db):
    from app.models import Clip
    from app.security.media_urls import media_url

    processed_space(client)
    clip = db.query(Clip).first()
    url = media_url("c", clip.id)
    ok = client.get(url)
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "audio/mpeg"
    assert ok.content[:3] == b"ID3" or ok.content[:2] == b"\xff\xfb" or ok.content[:2] == b"\xff\xf3"
    part = client.get(url, headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert client.get(url.replace("sig=", "sig=x")).status_code == 403
    expired = media_url("c", clip.id, ttl=-5)
    r = client.get(expired)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "media_link_expired"
