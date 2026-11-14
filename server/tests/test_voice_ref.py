"""참조 클립 고르기(app/voice/ref.py) 테스트. DB 를 쓰지 않는다."""

from __future__ import annotations

import math

from app.voice.ref import (
    CLIP_MAX_SEC,
    CLIP_MIN_SEC,
    MIN_TOTAL_SEC,
    TARGET_MAX_SEC,
    TARGET_MIN_SEC,
    RefCandidate,
    pick_reference,
)


def C(i: str, d: float, text: bool = True, pref: bool = False) -> RefCandidate:
    return RefCandidate(id=i, duration=d, has_text=text, preferred=pref)


def test_constants_match_shared_rule():
    assert MIN_TOTAL_SEC == 3.0
    assert (TARGET_MIN_SEC, TARGET_MAX_SEC) == (10.0, 15.0)
    assert (CLIP_MIN_SEC, CLIP_MAX_SEC) == (3.0, 15.0)


def test_empty_and_non_positive_are_not_usable():
    p = pick_reference([])
    assert p.clips == () and p.total_sec == 0 and p.usable is False
    p = pick_reference([C("a", 0), C("b", -2), C("c", math.nan), C("d", math.inf)])
    assert p.ids == [] and p.usable is False


def test_total_under_3s_is_not_usable():
    p = pick_reference([C("a", 1.0), C("b", 1.5)])
    assert p.ids == ["a", "b"]
    assert p.total_sec == 2.5
    assert p.usable is False


def test_exactly_3s_is_usable():
    p = pick_reference([C("a", 1.0), C("b", 2.0)])
    assert p.total_sec == 3.0 and p.usable is True


def test_text_first_then_preferred_length_then_input_order():
    cands = [
        C("no_text_good_len", 5, text=False),
        C("text_short", 2),
        C("text_good_1", 4),
        C("text_good_2", 4),
    ]
    p = pick_reference(cands)
    # 자막+3~15초(입력 순서) → 자막+짧음 → 자막 없음. 4+4=8, +2=10 → 멈춤
    assert p.ids == ["text_good_1", "text_good_2", "text_short"]
    assert p.total_sec == 10 and p.usable


def test_preferred_ids_come_first():
    cands = [C("a", 5), C("b", 5), C("src", 2, text=False)]
    p = pick_reference(cands, preferred_ids=["src"])
    assert p.ids[0] == "src"
    assert p.ids == ["src", "a", "b"]  # 2+5=7, +5=12 → 멈춤
    assert p.total_sec == 12


def test_preferred_flag_on_candidate_also_counts():
    p = pick_reference([C("a", 5), C("b", 5, pref=True)])
    assert p.ids[0] == "b"


def test_skip_candidate_that_would_exceed_15s():
    cands = [C("a", 8), C("b", 8), C("c", 3)]
    p = pick_reference(cands)
    # 8 → (8+8=16 > 15 건너뜀) → 8+3=11 ≥ 10 멈춤
    assert p.ids == ["a", "c"]
    assert p.total_sec == 11


def test_first_pick_may_exceed_15s_alone():
    # 3~15초 후보가 없고 첫 후보가 15초를 넘으면 그 하나는 고른다
    p = pick_reference([C("long", 20), C("x", 2)])
    assert p.ids == ["long"]
    assert p.total_sec == 20 and p.usable


def test_long_clip_ranked_after_preferred_length():
    p = pick_reference([C("long", 20), C("ok", 6)])
    # 'ok'(3~15초)가 먼저, 그다음 20초는 15 초과라 건너뜀
    assert p.ids == ["ok"]
    assert p.total_sec == 6 and p.usable


def test_stops_once_10s_reached():
    p = pick_reference([C(str(i), 5) for i in range(6)])
    assert p.ids == ["0", "1"]
    assert p.total_sec == 10


def test_never_exceeds_15s_after_first():
    p = pick_reference([C("a", 9), C("b", 7), C("c", 6), C("d", 0.5)])
    # 9 → 9+7=16 건너뜀 → 9+6=15 (≤15) 더함 → 15 ≥ 10 멈춤
    assert p.ids == ["a", "c"]
    assert p.total_sec == 15


def test_boundaries_3_and_15_are_preferred_length():
    p = pick_reference([C("short", 2.9), C("b3", 3.0)])
    assert p.ids[0] == "b3"
    p = pick_reference([C("over", 15.1), C("b15", 15.0)])
    assert p.ids == ["b15"]


def test_deterministic():
    cands = [C("a", 4, text=False), C("b", 2), C("c", 7), C("d", 3, pref=True), C("e", 12)]
    first = pick_reference(cands, ["b"])
    for _ in range(5):
        assert pick_reference(list(cands), ["b"]) == first
