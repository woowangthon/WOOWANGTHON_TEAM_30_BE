from __future__ import annotations

from tests.conftest import ApiClient, create_space, signup
from tests.helpers import ready_space


def chat(client, sid, message):
    r = client.post(f"/api/spaces/{sid}/chat", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


def test_chat_returns_original_clip(client, db):
    from app.models import Clip

    space, clips = ready_space(client)
    res = chat(client, space["id"], "밥은 먹었어?")
    assert res["matched"] is True
    assert res["picker"] == "mock"
    assert 1 <= len(res["clips"]) <= 3
    top = res["clips"][0]
    assert "밥" in top["transcript"]
    # 원칙 1: 답은 원본 클립 — transcript는 DB 자막과 글자 하나 다르지 않다
    for card in res["clips"]:
        row = db.get(Clip, card["clip_id"])
        assert card["transcript"] == row.text
        assert card["audio_url"].startswith("/api/media/c/")
        assert card["date"] == "2024-03-15"
        assert card["source_label"].startswith("통화 녹음")
    assert res["guide"]["text"]
    assert res["care"] is None


def test_excluded_voice_is_never_used(client):
    space, clips = ready_space(client)
    child_ids = {c["id"] for c in clips if not c["included"]}
    for q in ["면접 보고 왔어", "엄마는 저녁 먹었어?", "오늘 면접", "저녁"]:
        res = chat(client, space["id"], q)
        returned = {c["clip_id"] for c in res["clips"]} | {c["clip_id"] for c in res["nearby"]}
        assert not (returned & child_ids), q


def test_no_match_is_honest(client):
    space, _ = ready_space(client)
    res = chat(client, space["id"], "비트코인 사도 될까?")
    assert res["matched"] is False
    assert res["clips"] == []
    assert "딱 맞는 녹음은 없어요" in res["guide"]["text"]
    assert 1 <= len(res["nearby"]) <= 3
    assert all(c["reason"] == "가까운 추억" for c in res["nearby"])


def test_voice_not_chosen_yet_points_to_voice_review(client):
    from tests.test_pipeline import processed_space

    space, _ = processed_space(client)  # 올렸지만 '목소리 확인'을 아직 안 함
    res = chat(client, space["id"], "보고 싶어요")
    assert res["matched"] is False
    assert res["clips"] == [] and res["nearby"] == []
    assert "목소리 확인" in res["guide"]["text"]
    assert "가까운 추억" not in res["guide"]["text"]  # 보여 줄 것이 없으면 약속하지 않는다


def test_empty_space_points_to_upload(client):
    from tests.conftest import create_space, signup

    signup(client)
    space = create_space(client)
    res = chat(client, space["id"], "보고 싶어요")
    assert res["clips"] == [] and res["nearby"] == []
    assert "자료" in res["guide"]["text"]


def test_crisis_shows_help_before_clips(client):
    space, _ = ready_space(client)
    res = chat(client, space["id"], "엄마 따라가고 싶어. 이제 다 끝내고 싶어")
    assert res["care"]["level"] == "high"
    phones = [r["phone"] for r in res["care"]["resources"]]
    assert "109" in phones and "1577-0199" in phones
    assert res["clips"] or res["nearby"]  # 도움 안내 다음에 녹음도 함께


def test_watch_level(client):
    space, _ = ready_space(client)
    res = chat(client, space["id"], "요즘은 정말 견딜 수가 없어")
    assert res["care"]["level"] == "watch"


def test_sample_space_is_public_but_private_space_is_not(app, db):
    from app.models import Space

    owner = ApiClient(app)
    signup(owner)
    space = create_space(owner)
    anon = ApiClient(app)
    r = anon.post(f"/api/spaces/{space['id']}/chat", json={"message": "안녕"})
    assert r.status_code == 401
    row = db.get(Space, space["id"])
    row.is_sample = True
    db.commit()
    r = anon.post(f"/api/spaces/{space['id']}/chat", json={"message": "안녕"})
    assert r.status_code == 200
    # 샘플은 읽기 전용
    assert anon.patch(f"/api/spaces/{space['id']}", json={"name": "x"}).status_code in (401, 403)


def test_daily_chat_limit(app, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "chat_daily_limit", 2)
    c = ApiClient(app)
    space, _ = ready_space(c)
    assert chat(c, space["id"], "안녕")["remaining_today"] == 1
    assert chat(c, space["id"], "밥")["remaining_today"] == 0
    r = c.post(f"/api/spaces/{space['id']}/chat", json={"message": "또"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "chat_limit_reached"


def test_favorite_toggle(client):
    space, clips = ready_space(client)
    cid = next(c["id"] for c in clips if c["included"])
    r = client.put(f"/api/spaces/{space['id']}/clips/{cid}/favorite", json={"favorite": True})
    assert r.json() == {"favorite": True}
    res = chat(client, space["id"], "밥은 먹었어?")
    favs = [c for c in res["clips"] if c["clip_id"] == cid]
    if favs:
        assert favs[0]["favorite"] is True


def test_transcribe_without_stt_key_is_honest(client):
    space, _ = ready_space(client)
    r = client.post(
        f"/api/spaces/{space['id']}/transcribe",
        files={"audio": ("voice.webm", b"\x1a\x45\xdf\xa3" * 100, "audio/webm")},
    )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "stt_unavailable"
    assert "글로" in r.json()["error"]["message_ko"]


def test_talk_one_reply(client):
    """기억 대화: 답장은 하나. mock은 맞는 원본 하나를 답장으로, 위기·금지 주제는 안내."""
    space, clips = ready_space(client)
    sid = space["id"]
    text = next(c for c in clips if c["included"] and c["transcript"])["transcript"]

    def talk(msg):
        r = client.post(f"/api/spaces/{sid}/talk", json={"message": msg, "history": []})
        assert r.status_code == 200, r.text
        return r.json()

    res = talk(text)
    assert res["mode"] == "original" and len(res["clips"]) == 1
    assert res["text"] == res["clips"][0]["transcript"]  # 원본 자막 그대로
    crisis = talk("엄마 따라가고 싶어")
    assert crisis["mode"] == "crisis" and crisis["text"].startswith("잠깐 멈출게요") and crisis["clips"] == []
    assert talk("돈 좀 보내줘")["mode"] == "guide"


def test_talk_never_uses_other_voice(client):
    space, clips = ready_space(client)
    child = {c["id"] for c in clips if not c["included"]}
    for q in ["면접 보고 왔어", "엄마는 저녁 먹었어?"]:
        r = client.post(f"/api/spaces/{space['id']}/talk", json={"message": q}).json()
        assert not ({c["clip_id"] for c in r["clips"]} | {c["clip_id"] for c in r["sources"]}) & child
