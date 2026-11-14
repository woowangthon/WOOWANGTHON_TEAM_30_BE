"""기억 대화 검증: `python -m app.eval_talk [--live URL] [--out FILE]`

1) 안전 규칙 (AI 호출 없음, 언제나 실행)
   - fixtures/eval/talk_safety.json 의 위기 문장·금지 주제 문장·일상 문장에
     실제 서비스와 같은 규칙(app.care.crisis.rule_risk, app.services.talk.FORBIDDEN)을 건다.
2) 실제 대화 (--live 를 줄 때만, 배포된 서버의 샘플 공간에 POST /talk)
   - 골든 세트(fixtures/eval/queries.json) 30문항: 답장이 기대한 녹음을 쓰는지
     (원본 답장이면 그 녹음, AI가 만든 답이면 근거 녹음 안에)
   - 녹음에 없는 질문 4개: 지어내지 않고 안내로 끝나는지
   - 일상 메시지 20개(talk_safety.json normal): 답 종류와 근거
   - AI가 만든 답: 근거 녹음이 붙어 있는지, 금지 표현이 없는지
     (녹음에 없는 사실을 지어냈는지는 자동으로 판정하지 못해 결과 JSON을 사람이 읽고 판정한다)
   샘플 공간은 가상 인물 데이터라 실제 AI 공급자로 보내도 된다. 샘플 속도 제한(분당 20회)을 지킨다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from app.care.crisis import rule_risk
from app.config import FIXTURES_DIR
from app.services.talk import FORBIDDEN

PAUSE_SEC = 3.5


def load(name: str) -> dict:
    return json.loads((Path(FIXTURES_DIR) / name).read_text(encoding="utf-8"))


def safety() -> dict:
    s = load("eval/talk_safety.json")
    crisis = [(t, rule_risk(t)) for t in s["crisis"]]
    forbidden = [(t, bool(FORBIDDEN.search(t))) for t in s["forbidden"]]
    normal = [(t, rule_risk(t), bool(FORBIDDEN.search(t))) for t in s["normal"]]
    return {
        "crisis_total": len(crisis),
        "crisis_high": sum(1 for _, lv in crisis if lv == "high"),
        "crisis_watch": sum(1 for _, lv in crisis if lv == "watch"),
        "crisis_missed": [t for t, lv in crisis if lv == "none"],
        "crisis_watch_only": [t for t, lv in crisis if lv == "watch"],
        "forbidden_total": len(forbidden),
        "forbidden_blocked": sum(1 for _, b in forbidden if b),
        "forbidden_missed": [t for t, b in forbidden if not b],
        "normal_total": len(normal),
        "normal_false_crisis": [t for t, lv, _ in normal if lv == "high"],
        "normal_false_watch": [t for t, lv, _ in normal if lv == "watch"],
        "normal_false_forbidden": [t for t, _, f in normal if f],
    }


def live(base: str) -> dict:
    import httpx

    demo = load("demo/sample-space.json")
    ref_by_text = {c["text"].strip(): c["ref"] for c in demo["clips"]}
    q = load("eval/queries.json")
    headers = {"x-yeoun-request": "1", "content-type": "application/json"}
    with httpx.Client(base_url=base.rstrip("/"), timeout=90, headers=headers) as http:
        space_id = http.get("/api/config").json()["sample_space_id"]

        def ask(text: str) -> dict:
            for attempt in range(3):
                r = http.post(f"/api/spaces/{space_id}/talk", json={"message": text, "history": []})
                time.sleep(PAUSE_SEC)
                if r.status_code == 429 and attempt < 2:
                    time.sleep(30)
                    continue
                r.raise_for_status()
                return r.json()
            raise RuntimeError("rate limited")

        def refs(cards: list[dict]) -> list[str]:
            return [ref_by_text.get((c.get("transcript") or "").strip(), "?") for c in cards]

        rows = []
        for item in q["queries"]:
            r = ask(item["query"])
            used = refs(r["clips"]) if r["mode"] == "original" else refs(r["sources"])
            rows.append({
                "id": item["id"], "query": item["query"], "expected": item["expected"],
                "mode": r["mode"], "used": used, "text": r["text"],
                "hit": bool(set(used) & set(item["expected"])),
                "provider": r["provider"],
            })
        nomatch = []
        for item in q["no_match"]:
            r = ask(item["query"])
            nomatch.append({"id": item["id"], "query": item["query"], "mode": r["mode"], "text": r["text"],
                            "used": refs(r["clips"] + r["sources"])})
        # 일상 메시지: 녹음에 딱 맞는 답이 없을 때가 많아 'AI가 만든 말'이 주로 나온다
        everyday = []
        for text in load("eval/talk_safety.json")["normal"]:
            r = ask(text)
            everyday.append({"query": text, "mode": r["mode"], "text": r["text"],
                             "used": refs(r["clips"] if r["mode"] == "original" else r["sources"])})

    gen = [r for r in rows + everyday + nomatch if r["mode"] == "generated"]
    answered = [r for r in rows if r["mode"] in ("original", "generated")]
    return {
        "space_id": space_id,
        "golden_total": len(rows),
        "modes": dict(Counter(r["mode"] for r in rows)),
        "answered": len(answered),
        "answered_with_expected_clip": sum(1 for r in answered if r["hit"]),
        "original_with_expected_clip": sum(1 for r in answered if r["hit"] and r["mode"] == "original"),
        "generated_total": len(gen),
        "generated_with_sources": sum(1 for r in gen if r["used"]),
        "generated_forbidden": sum(1 for r in gen if FORBIDDEN.search(r["text"])),
        "providers": dict(Counter(r["provider"] for r in rows)),
        "no_match_total": len(nomatch),
        "no_match_guided": sum(1 for r in nomatch if r["mode"] == "guide"),
        "everyday_total": len(everyday),
        "everyday_modes": dict(Counter(r["mode"] for r in everyday)),
        "rows": rows,
        "no_match": nomatch,
        "everyday": everyday,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", help="배포된 API 주소 (예: https://yeoun-team30-api.onrender.com)")
    ap.add_argument("--out", help="결과 JSON 저장 경로")
    a = ap.parse_args()
    report = {"safety": safety()}
    if a.live:
        report["live"] = live(a.live)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    s = report["safety"]
    print(f"위기 문장 {s['crisis_total']}개: 위기 전환 {s['crisis_high']} · 주의만 {s['crisis_watch']} · 놓침 {len(s['crisis_missed'])}")
    print(f"금지 주제 {s['forbidden_total']}개: 막음 {s['forbidden_blocked']} · 놓침 {len(s['forbidden_missed'])}")
    print(f"일상 문장 {s['normal_total']}개: 위기 오탐 {len(s['normal_false_crisis'])} · 주의 오탐 {len(s['normal_false_watch'])} · 금지 오탐 {len(s['normal_false_forbidden'])}")
    if "live" in report:
        v = report["live"]
        print(f"골든 {v['golden_total']}문항: {v['modes']} · 답한 것 중 기대 녹음 사용 {v['answered_with_expected_clip']}/{v['answered']}")
        print(f"일상 메시지 {v['everyday_total']}개: {v['everyday_modes']}")
        print(f"AI가 만든 답 {v['generated_total']}개: 근거 있음 {v['generated_with_sources']} · 금지 표현 {v['generated_forbidden']}")
        print(f"녹음에 없는 질문 {v['no_match_total']}개: 안내로 끝남 {v['no_match_guided']}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
