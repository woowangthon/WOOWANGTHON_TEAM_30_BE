"""골든 세트로 top-3 검색 정확도 측정: `make eval` / `python -m app.eval`

- fixtures/eval/queries.json: 질문 30개 → 기대 클립 ref, 그리고 맞는 녹음이 없어야 하는 질문
- 샘플 공간 fixture로 실제 서비스와 같은 색인·검색·고르기 경로를 돌린다 (DB 없이)
- 기본은 mock(규칙). --llm 이면 설정된 LLM 공급자를 쓴다 (샘플은 가상 데이터라 정책상 허용)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

from app.ai import guard
from app.ai.llm import MockLLM
from app.config import FIXTURES_DIR, get_settings
from app.search.index import ClipDoc, SpaceIndex
from app.search.query import doc_tokens
from app.search.tokenizer import get_tokenizer, reset_tokenizer

ORIGIN = {"call": "통화 녹음", "video": "동영상", "voice_message": "음성 메시지", "ahead": "미리 남기기"}


@dataclass
class Report:
    tokenizer: str
    picker: str
    total: int = 0
    hits: int = 0
    retrieval_hits: int = 0
    rr_sum: float = 0.0
    no_match_total: int = 0
    no_match_ok: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def top3(self) -> float:
        return self.hits / self.total if self.total else 0.0


def _docs(data: dict) -> list[ClipDoc]:
    from app.routers.ahead import deck

    qtext = {c.id: c.text for c in deck().cards}
    docs = []
    for c in data["clips"]:
        q = qtext.get(c.get("question_id") or "")
        docs.append(
            ClipDoc(
                clip_id=c["ref"],
                text=c["text"],
                tokens=doc_tokens(c["text"], c.get("tags", []), q),
                date=None if c["date"].startswith("@") else c["date"],
                source=ORIGIN.get(c.get("source", ""), "녹음"),
                tags=c.get("tags", []),
                question=q,
            )
        )
    return docs


def run(tokenizer: str, use_llm: bool = False, verbose: bool = False) -> Report:
    s = get_settings()
    s.tokenizer = tokenizer  # type: ignore[assignment]
    reset_tokenizer()
    tok = get_tokenizer().name
    data = json.loads((FIXTURES_DIR / "demo" / "sample-space.json").read_text(encoding="utf-8"))
    golden = json.loads((FIXTURES_DIR / "eval" / "queries.json").read_text(encoding="utf-8"))
    person = data["space"]["person_name"]
    index = SpaceIndex(_docs(data))
    texts = {c["ref"]: c["text"] for c in data["clips"]}

    if use_llm:
        from app.ai import registry

        llm, _ = registry.build("llm", is_sample=True)
    else:
        llm = MockLLM()
    report = Report(tokenizer=tok, picker=llm.name)
    fallback = MockLLM()

    def pick(q: str) -> tuple[list[str], list[str]]:
        intent = guard.validate_intent(llm.parse_intent(q)) or guard.validate_intent(fallback.parse_intent(q))
        cands = index.search(q, intent, k=20)
        sel = guard.validate_selection(llm.select(q, intent, cands, person), cands)
        return [cid for cid, _ in sel.picks], [c.clip_id for c in cands]

    for item in golden["queries"]:
        report.total += 1
        picks, cands = pick(item["query"])
        expected = set(item["expected"])
        if expected & set(picks[:3]):
            report.hits += 1
        else:
            got = " / ".join(f"{p}:{texts[p][:18]}" for p in picks[:3]) or "(없음)"
            report.failures.append(f"{item['id']} '{item['query']}' 기대 {sorted(expected)} → {got}")
        if expected & set(cands[:3]):
            report.retrieval_hits += 1
        for rank, cid in enumerate(cands[:20], start=1):
            if cid in expected:
                report.rr_sum += 1 / rank
                break
    for item in golden.get("no_match", []):
        report.no_match_total += 1
        picks, _ = pick(item["query"])
        if not picks:
            report.no_match_ok += 1
        else:
            report.failures.append(f"{item['id']} '{item['query']}' 맞는 녹음이 없어야 하는데 {picks[:3]}")
    return report


def print_report(r: Report, verbose: bool) -> None:
    print(f"\n[토크나이저 {r.tokenizer} · 고르기 {r.picker}]")
    print(f"  top-3 정확도(최종 답)   : {r.hits}/{r.total} = {r.top3:.1%}")
    print(f"  검색 top-3(LLM 고르기 전): {r.retrieval_hits}/{r.total} = {r.retrieval_hits / max(1, r.total):.1%}")
    print(f"  MRR@20                 : {r.rr_sum / max(1, r.total):.3f}")
    print(f"  '맞는 녹음 없음' 정답    : {r.no_match_ok}/{r.no_match_total}")
    if r.failures and verbose:
        print("  틀린 질문:")
        for f in r.failures:
            print(f"   - {f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="여운 검색 정확도 평가")
    parser.add_argument("--llm", action="store_true", help="설정된 LLM 공급자로 고르기 (기본: mock 규칙)")
    parser.add_argument("--tokenizer", choices=["lite", "kiwi", "both"], default="both")
    parser.add_argument("--min", type=float, default=0.8, help="이보다 낮으면 실패(종료 코드 1)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()
    names = ["lite", "kiwi"] if args.tokenizer == "both" else [args.tokenizer]
    ok = True
    for name in names:
        r = run(name, use_llm=args.llm)
        if name == "kiwi" and r.tokenizer != "kiwi":
            print("\n[kiwi] kiwipiepy가 없어 건너뜀 (pip install '.[kiwi]')")
            continue
        print_report(r, verbose=not args.quiet)
        ok = ok and r.top3 >= args.min and r.no_match_ok == r.no_match_total
    print(f"\n기준: top-3 ≥ {args.min:.0%}, '맞는 녹음 없음' 모두 정답 → {'통과' if ok else '미달'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
