"""원칙 1·2 테스트: 말은 원본만, AI는 찾고 고르기만."""

from __future__ import annotations

import json
import re

from app.ai import guard
from app.ai.llm import Candidate
from tests.helpers import ready_space


def _use_replay(monkeypatch, tmp_path, entries):
    from app.config import get_settings

    path = tmp_path / "replay.json"
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "replay")
    monkeypatch.setattr(s, "llm_replay_path", path)


def test_llm_out_of_candidate_ids_and_fabricated_quotes_are_dropped(client, db, monkeypatch, tmp_path):
    from app.models import Clip

    space, clips = ready_space(client)
    mom_food = next(c for c in clips if "밥 꼭 챙겨" in c["text"])
    child = next(c for c in clips if not c["included"])
    _use_replay(
        monkeypatch,
        tmp_path,
        [
            {
                "kind": "intent",
                "match": "*",
                "output": {
                    "intent": "food",
                    "keywords": ["밥"],
                    "tags": ["음식", "없는태그"],
                    "risk": "none",
                },
            },
            {
                "kind": "select",
                "match": "*",
                "output": {
                    "picks": [
                        {"clip_id": "00000000-made-up", "reason": "지어낸 ID"},
                        {"clip_id": child["id"], "reason": "후보에 없는(제외된) 목소리"},
                        {"clip_id": mom_food["id"], "reason": '엄마가 "사랑한다 우리 딸"이라고 하셨어요'},
                    ],
                    "no_good_match": False,
                    "guide": "엄마: 밥은 먹었니? 엄마는 늘 네 걱정이야.",
                },
            },
        ],
    )
    r = client.post(f"/api/spaces/{space['id']}/chat", json={"message": "밥 먹었어"})
    res = r.json()
    assert res["picker"] == "replay"
    assert [c["clip_id"] for c in res["clips"]] == [mom_food["id"]]
    card = res["clips"][0]
    assert card["transcript"] == db.get(Clip, mom_food["id"]).text
    # 지어낸 인용·대사 형식은 어디에도 남지 않는다
    body = json.dumps(res, ensure_ascii=False)
    assert "사랑한다 우리 딸" not in body
    assert "엄마:" not in body
    assert "늘 네 걱정" not in body
    assert card["reason"]  # 템플릿 이유로 바뀐다
    assert res["guide"]["text"]


def test_llm_garbage_falls_back_to_rules(client, monkeypatch, tmp_path):
    space, _ = ready_space(client)
    _use_replay(
        monkeypatch, tmp_path, [{"kind": "select", "match": "*", "output": "이건 JSON 객체가 아니에요"}]
    )
    res = client.post(f"/api/spaces/{space['id']}/chat", json={"message": "밥은 먹었어?"}).json()
    assert res["picker"] == "mock"
    assert res["matched"] is True


def test_provider_error_falls_back(client, monkeypatch):
    """실제 공급자가 실패(시간 초과 등)해도 규칙 기반으로 계속 답한다."""
    from app.ai.base import ProviderError
    from app.services import chat as chat_mod

    space, _ = ready_space(client)

    class FailingLLM:
        name = "anthropic"
        live = True

        def parse_intent(self, *a, **k):
            raise ProviderError("timeout")

        def select(self, *a, **k):
            raise ProviderError("http_error")

    real_build = chat_mod.registry.build

    def fake_build(function, **kw):
        if function == "llm":
            return FailingLLM(), None
        return real_build(function, **kw)

    monkeypatch.setattr(chat_mod.registry, "build", fake_build)
    res = client.post(f"/api/spaces/{space['id']}/chat", json={"message": "밥은 먹었어?"}).json()
    assert res["matched"] is True
    assert res["picker"] == "mock"


def test_only_transcripts_carry_the_persons_words(client, db):
    """응답에서 그 사람의 말로 보일 수 있는 칸은 transcript뿐이고, 언제나 DB 자막 그대로다."""
    from app.models import Clip

    space, _ = ready_space(client)
    texts = {c.text for c in db.query(Clip).all()}
    for q in ["밥은 먹었어?", "추워", "면접 결과가 걱정돼", "보고 싶어"]:
        res = client.post(f"/api/spaces/{space['id']}/chat", json={"message": q}).json()
        for card in res["clips"] + res["nearby"]:
            assert card["transcript"] in texts
            assert not guard.fabricated_quotes(card["reason"] or "", [card["transcript"]])
        assert not guard.fabricated_quotes(res["guide"]["text"], [c["transcript"] for c in res["clips"]])


def test_guard_unit():
    cands = [
        Candidate(clip_id="a", text="밥은 꼭 챙겨 먹어라. 감기 조심하고."),
        Candidate(clip_id="b", text="사랑한다"),
    ]
    raw = {
        "picks": [
            {"clip_id": "a", "reason": '"밥은 꼭 챙겨 먹어라" 하셨던 통화예요'},
            {"clip_id": "zzz", "reason": "없음"},
            {"clip_id": "a", "reason": "중복"},
            {"clip_id": "b", "reason": "‘보고 싶다 우리 딸’이라고 하셨어요"},
        ],
        "no_good_match": False,
        "guide": "할머니: 사랑한다",
    }
    out = guard.validate_selection(raw, cands)
    assert out.picks[0] == ("a", '"밥은 꼭 챙겨 먹어라" 하셨던 통화예요')  # 실제 자막 인용은 허용
    assert out.picks[1] == ("b", None)  # 자막에 없는 인용 → 버림
    assert out.dropped_ids == 2
    assert out.guide is None  # 대사 형식
    assert guard.validate_tagging({"clips": [{"clip_id": "a", "tags": ["음식", "가짜"]}]}, ["a"]) == {
        "a": ["음식"]
    }


def test_no_voice_synthesis_or_impersonation_endpoints(app):
    # speak(?!er): 화자(speaker) 고르기 주소(/speakers/{id})는 말하기·합성이 아니므로 제외
    bad = re.compile(r"tts|synth|clone|speak(?!er)|persona|imperson|generate", re.I)
    paths = [getattr(r, "path", "") for r in app.routes]
    assert not [p for p in paths if bad.search(p)]
    import pkgutil

    import app.ai as ai_pkg

    modules = {m.name for m in pkgutil.iter_modules(ai_pkg.__path__)}
    assert not {m for m in modules if bad.search(m)}
