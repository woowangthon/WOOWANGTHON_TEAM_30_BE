"""샘플 공간 seed와 골든 세트 평가."""

from __future__ import annotations

import json
import shutil

from app.config import FIXTURES_DIR
from tests.conftest import ApiClient


def test_eval_gate_with_mock():
    from app.eval import run

    r = run("lite")
    assert r.top3 >= 0.8, r.failures
    assert r.no_match_ok == r.no_match_total, r.failures


def test_seed_creates_public_sample(app, db):
    from app.models import Asset, Clip
    from app.seed import seed_sample

    sid = seed_sample(force=True)
    assert db.query(Clip).filter_by(space_id=sid).count() == 40
    assert db.query(Asset).filter_by(space_id=sid, kind="photo").count() == 12
    # 다시 불러도 바뀐 게 없으면 그대로
    assert seed_sample() == sid

    anon = ApiClient(app)
    cfg = anon.get("/api/config").json()
    assert cfg["sample_space_id"] == sid
    space = anon.get(f"/api/spaces/{sid}").json()
    assert space["is_sample"] and space["name"].startswith("[샘플]")
    assert space["role"] == "viewer"
    res = anon.post(f"/api/spaces/{sid}/chat", json={"message": "할머니 김치찌개 어떻게 끓였어?"}).json()
    assert res["matched"]
    top = res["clips"][0]
    assert "김치찌개" in top["transcript"]
    assert top["audio_status"] == "placeholder" and top["audio_url"] is None
    tl = anon.get(f"/api/spaces/{sid}/timeline").json()
    assert tl["total"] == 52
    assert len(tl["on_this_day"]) >= 1  # '@one_year_ago' 클립
    # 샘플은 읽기 전용
    assert anon.post(f"/api/spaces/{sid}/assets", files={"file": ("a.mp3", b"x")}, data={"consent": "true"}).status_code in (
        401,
        403,
    )


def test_seed_uses_team_recordings_when_present(db, tmp_path, monkeypatch):
    from app import seed
    from app.models import Clip
    from app.pipeline.media import make_test_tone

    demo = tmp_path / "demo"
    demo.mkdir()
    shutil.copy(FIXTURES_DIR / "demo" / "sample-space.json", demo / "sample-space.json")
    make_test_tone(demo / "demo-04.wav", seconds=4)
    monkeypatch.setattr(seed, "DEMO_DIR", demo)
    monkeypatch.setattr(seed, "SAMPLE_JSON", demo / "sample-space.json")
    sid = seed.seed_sample(force=True)
    clip = db.query(Clip).filter_by(space_id=sid, ref="demo-04").one()
    assert clip.audio_status == "ready"
    assert 3.5 <= clip.end_sec <= 5
    others = db.query(Clip).filter(Clip.space_id == sid, Clip.ref != "demo-04").all()
    assert all(c.audio_status == "placeholder" for c in others)


def test_one_year_ago_is_before_memorial_day():
    import datetime as dt

    from app.seed import one_year_ago_date

    d = one_year_ago_date(dt.date(2024, 12, 3), dt.date(2026, 11, 9))
    assert d == dt.date(2024, 11, 9)
    assert one_year_ago_date(None, dt.date(2026, 11, 9)) == dt.date(2025, 11, 9)


def test_recording_script_matches_fixture():
    data = json.loads((FIXTURES_DIR / "demo" / "sample-space.json").read_text(encoding="utf-8"))
    script = (FIXTURES_DIR.parent / "docs" / "demo-recording-script.md").read_text(encoding="utf-8")
    for c in data["clips"]:
        assert c["text"] in script, c["ref"]
