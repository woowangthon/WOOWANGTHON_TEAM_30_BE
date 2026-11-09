"""LLM 출력 검증 (원칙 1·2).

- 스키마로 검증하고, 후보 목록에 없는 clip_id는 버린다.
- 자막에 없는 말을 따옴표로 인용하면(지어낸 인용) 그 문장을 버린다.
- '할머니: …' 같은 대사 형식(그 사람인 척)은 버린다.
- 버린 이유는 로그에 남기되 내용은 남기지 않는다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.ai.llm import Candidate
from app.schemas import CARE_LEVEL_VALUES, INTENT_VALUES, TAG_VALUES, LLMIntent

log = logging.getLogger("yeoun.guard")

MAX_REASON = 120
MAX_GUIDE = 200

_QUOTE = re.compile(r"[\"“”]([^\"“”]{2,})[\"“”]|[‘’']([^‘’']{2,})[‘’']|[「『]([^」』]{2,})[」』]")
_DIALOGUE = re.compile(r"(^|\n)\s*[^\s:：]{1,12}\s*[:：]\s*\S")
_PUNCT = re.compile(r"[\s.,!?~…·\-–—\"'“”‘’「」『』()\[\]]+")


def _norm(s: str) -> str:
    return _PUNCT.sub("", s)


def quoted_spans(text: str) -> list[str]:
    return [next(g for g in m.groups() if g) for m in _QUOTE.finditer(text)]


def fabricated_quotes(text: str, allowed: list[str]) -> list[str]:
    """allowed(실제 자막) 어디에도 없는 인용 구절."""
    pool = [_norm(a) for a in allowed]
    bad = []
    for q in quoted_spans(text):
        nq = _norm(q)
        if nq and not any(nq in p for p in pool):
            bad.append(q)
    return bad


def is_safe_service_text(text: str, allowed: list[str]) -> bool:
    if not text.strip():
        return False
    if fabricated_quotes(text, allowed):
        return False
    if _DIALOGUE.search(text):
        return False
    return True


def validate_intent(raw: Any) -> LLMIntent | None:
    if not isinstance(raw, dict):
        return None
    intent = raw.get("intent") if raw.get("intent") in INTENT_VALUES else "general"
    risk = raw.get("risk") if raw.get("risk") in CARE_LEVEL_VALUES else "none"
    kws = [str(k)[:20] for k in (raw.get("keywords") or []) if isinstance(k, str) and k.strip()][:8]
    tags = []
    for t in raw.get("tags") or []:
        if t in TAG_VALUES and t not in tags:
            tags.append(t)
    try:
        return LLMIntent(intent=intent, keywords=kws, tags=tags[:5], risk=risk)
    except ValidationError:
        return None


@dataclass
class CheckedSelection:
    picks: list[tuple[str, str | None]] = field(default_factory=list)
    no_good_match: bool = False
    guide: str | None = None
    dropped_ids: int = 0
    dropped_texts: int = 0
    valid: bool = True


def validate_selection(raw: Any, candidates: list[Candidate], max_picks: int = 3) -> CheckedSelection:
    out = CheckedSelection()
    if not isinstance(raw, dict) or not isinstance(raw.get("picks", []), list):
        out.valid = False
        return out
    by_id = {c.clip_id: c for c in candidates}
    seen: set[str] = set()
    for p in raw.get("picks") or []:
        if not isinstance(p, dict):
            out.dropped_ids += 1
            continue
        cid = p.get("clip_id")
        if not isinstance(cid, str) or cid not in by_id or cid in seen:
            out.dropped_ids += 1  # 후보 밖 ID는 버린다
            continue
        seen.add(cid)
        reason = p.get("reason")
        if isinstance(reason, str):
            reason = reason.strip()[:MAX_REASON]
            if not is_safe_service_text(reason, [by_id[cid].text, by_id[cid].question or ""]):
                out.dropped_texts += 1
                reason = None
        else:
            reason = None
        out.picks.append((cid, reason or None))
        if len(out.picks) >= max_picks:
            break
    out.no_good_match = bool(raw.get("no_good_match")) and not out.picks
    guide = raw.get("guide")
    if isinstance(guide, str):
        guide = guide.strip()[:MAX_GUIDE]
        allowed = [by_id[c].text for c, _ in out.picks]
        if not is_safe_service_text(guide, allowed):
            out.dropped_texts += 1
            guide = None
    else:
        guide = None
    out.guide = guide
    if out.dropped_ids or out.dropped_texts:
        log.info("llm_output_filtered ids=%d texts=%d", out.dropped_ids, out.dropped_texts)
    return out


def validate_tagging(raw: Any, ids: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not isinstance(raw, dict):
        return result
    wanted = set(ids)
    for item in raw.get("clips") or []:
        if not isinstance(item, dict) or item.get("clip_id") not in wanted:
            continue
        tags = []
        for t in item.get("tags") or []:
            if t in TAG_VALUES and t not in tags:  # 정해진 목록 밖 태그는 버린다
                tags.append(t)
        result[item["clip_id"]] = tags[:5]
    return result
