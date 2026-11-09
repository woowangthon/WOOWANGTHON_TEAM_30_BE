from __future__ import annotations

from tests.conftest import ApiClient, create_space, signup
from tests.test_pipeline import processed_space, upload


def test_voice_review_flow(client, db):
    space, asset = processed_space(client)
    sid = space["id"]
    review = client.get(f"/api/spaces/{sid}/voices").json()
    assert review["pending_count"] == 1
    item = review["assets"][0]
    assert item["diarized"] is True
    assert item["needs_review"] is True
    labels = [s["label"] for s in item["speakers"]]
    assert labels == ["목소리 1", "목소리 2"]
    spk_child, spk_mom = item["speakers"]
    assert spk_mom["clip_count"] == 3
    assert 1 <= len(spk_mom["samples"]) <= 3
    assert all(s["audio_url"] for s in spk_mom["samples"])

    r = client.patch(f"/api/spaces/{sid}/speakers/{spk_mom['id']}", json={"role": "person"})
    assert r.status_code == 200
    # 아직 한 화자가 남아 확인 대기
    assert client.get(f"/api/spaces/{sid}").json()["counts"]["pending_voice"] == 1
    client.patch(f"/api/spaces/{sid}/speakers/{spk_child['id']}", json={"role": "other"})
    sp = client.get(f"/api/spaces/{sid}").json()
    assert sp["counts"]["pending_voice"] == 0
    assert sp["counts"]["person_clips"] == 3

    clips = client.get(f"/api/spaces/{sid}/assets/{asset['id']}/clips").json()["clips"]
    assert [c["included"] for c in clips] == [False, True, False, True, True]

    # 클립별 제외·포함
    r = client.patch(f"/api/spaces/{sid}/clips/{clips[4]['id']}", json={"include_override": False})
    assert r.json()["included"] is False
    r = client.patch(f"/api/spaces/{sid}/clips/{clips[0]['id']}", json={"include_override": True})
    assert r.json()["included"] is True
    assert client.get(f"/api/spaces/{sid}").json()["counts"]["person_clips"] == 3
    r = client.patch(f"/api/spaces/{sid}/clips/{clips[0]['id']}", json={"clear_override": True})
    assert r.json()["included"] is False


def test_caption_edit_reindexes(client, db):
    from app.models import Clip

    space, asset = processed_space(client)
    sid = space["id"]
    clips = client.get(f"/api/spaces/{sid}/assets/{asset['id']}/clips").json()["clips"]
    target = clips[1]
    r = client.patch(
        f"/api/spaces/{sid}/clips/{target['id']}", json={"text": "그래, 고생 많았다. 된장찌개 끓여 놓을게."}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["text_edited"] is True
    row = db.get(Clip, target["id"])
    db.refresh(row)
    assert row.text_original.startswith("그래, 고생 많았다. 결과가")
    assert "된장찌개" in row.tokens


def test_viewer_cannot_change_voices(app, db):
    from app.models import Member, User

    a = ApiClient(app)
    v = ApiClient(app)
    signup(a, "a@example.com")
    signup(v, "v@example.com")
    space = create_space(a)
    assert upload(a, space["id"]).status_code == 201
    from app.worker import run_pending_jobs

    run_pending_jobs()
    viewer = db.query(User).filter_by(email="v@example.com").one()
    db.add(Member(space_id=space["id"], user_id=viewer.id, role="viewer"))
    db.commit()
    review = v.get(f"/api/spaces/{space['id']}/voices").json()
    spk = review["assets"][0]["speakers"][0]
    r = v.patch(f"/api/spaces/{space['id']}/speakers/{spk['id']}", json={"role": "person"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
