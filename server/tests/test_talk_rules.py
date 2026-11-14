"""기억 대화의 판단 규칙 (DB·AI 없이): LLM 위험도, 만든 답을 내보낼지."""

from __future__ import annotations

from app.care.crisis import combine
from app.services.talk import decide_generated, llm_risk

ALLOWED = {"a", "b", "c", "d"}
RELATED = {"a", "b"}


def raw(**kw):
    base = {"refuse": False, "use_clip_id": "", "text": "밥은 묵었나?", "source_clip_ids": ["a"], "kind": "feeling", "risk": "none"}
    base.update(kw)
    return base


def test_llm_risk_can_raise_but_not_lower():
    assert combine("none", llm_risk(raw(risk="high"))) == "high"
    assert combine("none", llm_risk(raw(risk="watch"))) == "watch"
    assert combine("high", llm_risk(raw(risk="none"))) == "high"
    assert combine("watch", llm_risk(raw(risk="nonsense"))) == "watch"
    assert combine("none", llm_risk({})) == "none"


def test_feeling_reply_may_use_tone_only_sources():
    assert decide_generated(raw(kind="feeling", source_clip_ids=["c"]), ALLOWED, RELATED) == ("밥은 묵었나?", ["c"])


def test_fact_reply_needs_a_related_source():
    # 녹음에 없는 경험·정보를 말투 참고 녹음만으로 답한 경우 → 버림
    assert decide_generated(raw(kind="fact", source_clip_ids=["c", "d"]), ALLOWED, RELATED) is None
    # kind가 없으면 사실 답으로 보고 같은 기준
    no_kind = raw(source_clip_ids=["c"])
    del no_kind["kind"]
    assert decide_generated(no_kind, ALLOWED, RELATED) is None
    # 관련 녹음이 근거에 있으면 내보내고, 관련 녹음을 앞에 둔다
    assert decide_generated(raw(kind="fact", source_clip_ids=["c", "b"]), ALLOWED, RELATED) == ("밥은 묵었나?", ["b", "c"])


def test_refused_empty_unknown_or_forbidden_is_dropped():
    assert decide_generated(raw(refuse=True), ALLOWED, RELATED) is None
    assert decide_generated(raw(text="  "), ALLOWED, RELATED) is None
    assert decide_generated(raw(source_clip_ids=["zzz"]), ALLOWED, RELATED) is None
    assert decide_generated(raw(text="통장 비밀번호는 1234다"), ALLOWED, RELATED) is None


def test_sources_are_deduplicated_and_capped():
    out = decide_generated(raw(source_clip_ids=["a", "a", "c", "d", "b"]), ALLOWED, RELATED)
    assert out is not None and out[1] == ["a", "c", "d"]
