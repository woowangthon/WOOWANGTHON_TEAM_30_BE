"""마음 돌봄: 위기 신호 규칙, 밤 시간 알림 금지, 생일·기일 알림."""

from __future__ import annotations

import datetime as dt

import pytest

from app.care.crisis import care_notice, combine, rule_risk
from app.routers.notices import KST, build_notices, is_quiet
from tests.conftest import create_space, signup


@pytest.mark.parametrize(
    "text",
    [
        "죽고 싶어",
        "그냥 죽고싶다",
        "엄마 따라가고 싶어",
        "할머니 곁으로 가고 싶다",
        "살기 싫어",
        "더 이상 못 살겠어",
        "자살하면 엄마 만날 수 있을까",
        "약을 모아 두었어",
        "사라지고 싶어",
        "손목을 긋고 싶어",
    ],
)
def test_high_risk_phrases(text):
    assert rule_risk(text) == "high"


@pytest.mark.parametrize("text", ["견딜 수가 없어", "다 포기하고 싶어", "아무도 없어 이제", "너무 괴로워"])
def test_watch_phrases(text):
    assert rule_risk(text) == "watch"


@pytest.mark.parametrize(
    "text",
    [
        "배고파 죽겠다",
        "더워 죽겠네",
        "엄마 보러 가고 싶어",
        "엄마 김치찌개 먹고 싶어",
        "시장에 따라가던 기억",
        "웃겨 죽는 줄",
    ],
)
def test_everyday_phrases_are_not_flagged(text):
    assert rule_risk(text) == "none"


def test_llm_can_raise_but_not_lower():
    assert combine("none", "high") == "high"
    assert combine("high", "none") == "high"
    assert combine("watch", None) == "watch"


def test_care_notice_has_hotlines():
    n = care_notice("high")
    phones = {r.phone for r in n.resources}
    assert {"109", "1577-0199"} <= phones
    assert "탓" not in n.message
    assert care_notice("none") is None


@pytest.mark.parametrize(
    "hour,quiet",
    [(21, False), (22, True), (23, True), (0, True), (3, True), (7, True), (8, False), (12, False)],
)
def test_quiet_hours_kst(hour, quiet):
    now = dt.datetime(2026, 5, 1, hour, 30, tzinfo=KST)
    assert is_quiet(now) is quiet
    # UTC로 넘어와도 한국 시간 기준
    assert is_quiet(now.astimezone(dt.UTC)) is quiet


def test_birthday_and_memorial_notices(client, db):
    from app.models import User

    signup(client)
    today = dt.date(2026, 5, 10)
    client.post(
        "/api/spaces",
        json={"name": "엄마", "person_name": "엄마", "memorial_day": "2024-05-11", "birthday": "1955-05-10"},
    )
    user = db.query(User).one()
    day = dt.datetime(2026, 5, 10, 10, 0, tzinfo=KST)
    notices = build_notices(db, user, day)
    kinds = sorted(n.kind for n in notices)
    assert kinds == ["birthday", "memorial"]
    memorial = next(n for n in notices if n.kind == "memorial")
    assert memorial.title == "내일은 기일이에요"
    # 밤에는 띄우지 않는다
    assert build_notices(db, user, dt.datetime(2026, 5, 10, 23, 0, tzinfo=KST)) == []
    # 닫으면 다시 나오지 않는다
    r = client.post(f"/api/notices/{memorial.id}/dismiss")
    assert r.status_code == 204
    again = build_notices(db, user, day)
    assert [n.kind for n in again] == ["birthday"]
    assert today.month == 5


def test_notices_endpoint_requires_login(client):
    assert client.get("/api/notices").status_code == 401
    signup(client)
    create_space(client)
    assert client.get("/api/notices").status_code == 200


def test_collections(client):
    from tests.helpers import ready_space

    space, clips = ready_space(client)
    sid = space["id"]
    person = [c["id"] for c in clips if c["included"]]
    other = [c["id"] for c in clips if not c["included"]]
    r = client.post(
        f"/api/spaces/{sid}/collections", json={"title": "엄마의 잔소리 모음", "clip_ids": person + other}
    )
    assert r.status_code == 201
    col = r.json()
    assert col["clip_ids"] == person  # 그 사람 목소리만 담긴다
    assert [c["transcript"] for c in col["clips"]]
    assert len(client.get(f"/api/spaces/{sid}/collections").json()["collections"]) == 1
    r = client.patch(f"/api/spaces/{sid}/collections/{col['id']}", json={"clip_ids": person[:1]})
    assert r.json()["clip_ids"] == person[:1]
    assert client.delete(f"/api/spaces/{sid}/collections/{col['id']}").status_code == 204
