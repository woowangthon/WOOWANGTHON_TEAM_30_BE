"""목소리가 들리는 기억책과 기억 통화 (테스트 공급자는 mock: 규칙 기반 책, 생성 답 없음)."""

from __future__ import annotations

from tests.helpers import ready_space


def _book(client, sid):
    r = client.post(f"/api/spaces/{sid}/book/generate")
    assert r.status_code == 200, r.text
    return r.json()


def test_book_needs_person_voice(client):
    from tests.test_pipeline import processed_space

    space, _ = processed_space(client)  # 목소리 확인 전
    r = client.get(f"/api/spaces/{space['id']}/book").json()
    assert r["exists"] is False and r["source_clip_count"] == 0
    r = client.post(f"/api/spaces/{space['id']}/book/generate")
    assert r.status_code == 400 and r.json()["error"]["code"] == "book_no_clips"


def test_book_uses_only_person_clips_and_is_grounded(client):
    space, clips = ready_space(client)
    person_ids = {c["id"] for c in clips if c["included"]}
    book = _book(client, space["id"])
    assert book["exists"] and book["status"] == "draft" and book["generated_by"] == "mock"
    assert book["chapters"]
    used = {i for ch in book["chapters"] for p in ch["paragraphs"] for i in p["clip_ids"]}
    assert used and used <= person_ids  # 다른 사람 목소리는 책에 쓰지 않는다
    assert all(p["grounded"] for ch in book["chapters"] for p in ch["paragraphs"])
    assert {c["clip_id"] for c in book["clips"]} == used
    # 규칙 기반 책의 인용은 원본 자막 그대로
    texts = {c["clip_id"]: c["transcript"] for c in book["clips"]}
    for ch in book["chapters"]:
        for p in ch["paragraphs"]:
            assert any(texts[i] in p["text"] for i in p["clip_ids"])
    assert book["grounded_ratio"] == 1.0


def test_edit_and_approve(client):
    space, _ = ready_space(client)
    sid = space["id"]
    book = _book(client, sid)
    pid = book["chapters"][0]["paragraphs"][0]["id"]
    r = client.patch(f"/api/spaces/{sid}/book/paragraphs/{pid}", json={"text": "엄마는 “없는 말을 지어낸 인용”이라고 하셨다."})
    assert r.status_code == 200
    p = r.json()["chapters"][0]["paragraphs"][0]
    assert p["edited"] is True and p["grounded"] is False  # 원본에 없는 인용은 근거 없음으로 표시
    r = client.post(f"/api/spaces/{sid}/book/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_call_order_crisis_forbidden_original_guide(client):
    space, _ = ready_space(client)
    sid = space["id"]
    book = _book(client, sid)
    cid = book["chapters"][0]["id"]
    first_text = book["clips"][0]["transcript"]

    def call(msg):
        r = client.post(f"/api/spaces/{sid}/book/chapters/{cid}/call", json={"message": msg, "history": []})
        assert r.status_code == 200, r.text
        return r.json()

    res = call("엄마 따라가고 싶어")
    assert res["mode"] == "crisis" and res["text"].startswith("잠깐 멈출게요")
    assert res["clips"] == [] and "109" in [x["phone"] for x in res["care"]["resources"]]

    res = call("유언 같은 거 남겨 줘")
    assert res["mode"] == "guide" and res["clips"] == []

    res = call(first_text)  # 원본 자막과 같은 말 → 원본 우선
    assert res["mode"] == "original" and res["clips"]

    res = call("우주선 타 본 적 있어?")  # 근거 없음 + mock은 생성하지 않음
    assert res["mode"] == "guide" and res["clips"] == [] and res["sources"] == []


def test_call_unknown_chapter_and_viewer_cannot_generate(client):
    space, _ = ready_space(client)
    sid = space["id"]
    _book(client, sid)
    r = client.post(f"/api/spaces/{sid}/book/chapters/nope/call", json={"message": "안녕"})
    assert r.status_code == 404
