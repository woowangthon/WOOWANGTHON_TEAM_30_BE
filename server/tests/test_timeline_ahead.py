from __future__ import annotations

import datetime as dt

from app.worker import run_pending_jobs
from tests.conftest import ApiClient, create_space, signup
from tests.helpers import ready_space


def _tone(tmp_path, name="answer.wav", seconds=8):
    from app.pipeline.media import make_test_tone

    p = tmp_path / name
    make_test_tone(p, seconds=seconds)
    return p


def test_question_deck_has_enough_korean_cards(client):
    deck = client.get("/api/questions").json()
    assert len(deck["cards"]) >= 60
    assert {c["id"] for c in deck["categories"]} >= {"childhood", "to_family", "life_advice", "food"}
    assert all(any("가" <= ch <= "힣" for ch in c["text"]) for c in deck["cards"])


def test_recording_link_full_flow(app, db, tmp_path):
    from app.models import Asset, Clip, RecordingLink, Speaker

    owner = ApiClient(app)
    signup(owner)
    space = create_space(owner)
    sid = space["id"]
    r = owner.post(
        f"/api/spaces/{sid}/links",
        json={
            "question_ids": ["q001", "q042"],
            "custom_questions": ["우리 강아지 이름은 누가 지었어요?"],
            "sender_name": "지은",
        },
    )
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["url"].startswith("http://localhost:3000/r/")  # Origin이 없으면 개발 기본값
    assert len(link["questions"]) == 3
    token = link["url"].rsplit("/", 1)[-1]
    # 토큰 원문은 DB에 없다
    row = db.query(RecordingLink).one()
    assert token not in row.token_hash
    assert owner.get(f"/api/spaces/{sid}/links").json()["links"][0]["url"] is None

    rec = ApiClient(app)  # 로그인 없음
    session = rec.get(f"/api/record/{token}").json()
    assert session["sender_name"] == "지은"
    assert "새 말이나 새 음성을 만들지 않아요" in session["consent_text"]
    wav = _tone(tmp_path)
    with wav.open("rb") as f:
        r = rec.post(
            f"/api/record/{token}/answers",
            data={"question_id": "q042"},
            files={"audio": ("a.wav", f, "audio/wav")},
        )
    assert r.status_code == 403 and r.json()["error"]["code"] == "consent_needed"
    assert rec.post(f"/api/record/{token}/consent").status_code == 204
    for _ in range(2):  # 다시 하기: 두 번째 녹음이 첫 번째를 대신한다
        with wav.open("rb") as f:
            r = rec.post(
                f"/api/record/{token}/answers",
                data={"question_id": "q042"},
                files={"audio": ("a.wav", f, "audio/wav")},
            )
        assert r.status_code == 201, r.text
    assert db.query(Asset).filter_by(question_id="q042").count() == 1
    run_pending_jobs()

    asset = db.query(Asset).filter_by(question_id="q042").one()
    db.refresh(asset)
    assert asset.status == "ready", asset.error_code
    assert asset.source == "ahead" and asset.voice_reviewed
    spk = db.query(Speaker).filter_by(asset_id=asset.id).one()
    assert spk.role == "person"
    clips = db.query(Clip).filter_by(asset_id=asset.id).all()
    assert len(clips) == 1  # 자막 없는 구간은 30초 안에서 이어 붙인다
    assert any(t in clips[0].tags for t in ("요리", "음식"))  # 질문 태그

    # 자막이 없어도(음성 인식 꺼짐) 질문과 연결되어 찾을 수 있다
    res = owner.post(
        f"/api/spaces/{sid}/chat", json={"message": "제일 자신 있는 음식 만드는 법 알려 줘"}
    ).json()
    assert res["matched"] is True
    assert res["clips"][0]["question"] == asset.question_text

    progress = owner.get(f"/api/spaces/{sid}/links").json()["links"][0]
    assert progress["answered_count"] == 1
    assert rec.post(f"/api/record/{token}/complete").status_code == 204
    # 1회용: 끝낸 링크는 다시 쓸 수 없다
    again = rec.get(f"/api/record/{token}")
    assert again.status_code == 410
    assert again.json()["error"]["code"] == "link_expired"


def test_expired_and_revoked_links(app, db):
    from app.models import RecordingLink

    owner = ApiClient(app)
    signup(owner)
    sid = create_space(owner)["id"]
    a = owner.post(f"/api/spaces/{sid}/links", json={"question_ids": ["q001"]}).json()
    b = owner.post(f"/api/spaces/{sid}/links", json={"question_ids": ["q002"]}).json()
    row = db.get(RecordingLink, a["id"])
    row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    db.commit()
    rec = ApiClient(app)
    assert rec.get(f"/api/record/{a['url'].rsplit('/', 1)[-1]}").status_code == 410
    assert owner.get(f"/api/spaces/{sid}/links").json()["links"][1]["status"] == "expired"
    owner.post(f"/api/spaces/{sid}/links/{b['id']}/revoke")
    assert rec.get(f"/api/record/{b['url'].rsplit('/', 1)[-1]}").status_code == 410
    assert rec.get("/api/record/not-a-real-token").status_code == 404


def test_link_validation(client):
    signup(client)
    sid = create_space(client)["id"]
    assert client.post(f"/api/spaces/{sid}/links", json={"question_ids": []}).status_code == 400
    assert client.post(f"/api/spaces/{sid}/links", json={"question_ids": ["nope"]}).status_code == 400


def test_timeline_groups_and_filters(client, db):
    from app.models import Asset

    space, clips = ready_space(client)
    sid = space["id"]
    tl = client.get(f"/api/spaces/{sid}/timeline").json()
    assert tl["total"] == 3
    assert tl["days"][0]["date"] == "2024-03-15"
    assert "(금)" in tl["days"][0]["label"]
    assert all(i["kind"] == "clip" for i in tl["days"][0]["items"])
    assert tl["tag_counts"]["음식"] >= 1

    food = client.get(f"/api/spaces/{sid}/timeline", params={"tag": "음식"}).json()
    assert 1 <= food["total"] < 3
    assert client.get(f"/api/spaces/{sid}/timeline", params={"favorites": True}).json()["total"] == 0
    cid = next(c["id"] for c in clips if c["included"])
    client.put(f"/api/spaces/{sid}/clips/{cid}/favorite", json={"favorite": True})
    assert client.get(f"/api/spaces/{sid}/timeline", params={"favorites": True}).json()["total"] == 1

    # 1년 전 오늘
    from app.routers.timeline import today_kst

    asset = db.query(Asset).filter_by(space_id=sid).first()
    t = today_kst()
    asset.recorded_at = (
        t.replace(year=t.year - 1) if not (t.month == 2 and t.day == 29) else t.replace(year=t.year - 4)
    )
    db.commit()
    tl = client.get(f"/api/spaces/{sid}/timeline").json()
    assert len(tl["on_this_day"]) == 3


def test_timeline_privacy(app):
    a = ApiClient(app)
    space, _ = ready_space(a)
    b = ApiClient(app)
    signup(b, "b@example.com")
    assert b.get(f"/api/spaces/{space['id']}/timeline").status_code == 404


def test_link_url_uses_browser_origin_when_not_configured(client):
    signup(client)
    sid = create_space(client)["id"]
    r = client.post(
        f"/api/spaces/{sid}/links",
        json={"question_ids": ["q001"]},
        headers={"origin": "https://yeoun-web.onrender.com"},
    )
    assert r.json()["url"].startswith("https://yeoun-web.onrender.com/r/")
    # 이상한 Origin(http 외부 주소)은 믿지 않는다
    r = client.post(
        f"/api/spaces/{sid}/links", json={"question_ids": ["q001"]}, headers={"origin": "http://evil.example"}
    )
    assert r.json()["url"].startswith("http://localhost:3000/r/")
