"""그 사람의 성격·말투 분석 (페르소나 카드).

'그 사람'으로 확인된 녹음 자막에서 말하기 특징만 뽑는다: 듣는 가족을 부르는 말, 자기 호칭, 어미·사투리,
자주 쓰는 표현, 자주 나오는 이야기 주제. 성격을 짐작해 평가하지 않고 자막에 나온 것만 쓴다.
녹음이 바뀌지 않았으면(공간의 index_version이 같으면) 만들어 둔 카드를 다시 쓴다.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.ai.base import ProviderError
from app.models import Space

log = logging.getLogger("yeoun.persona")

_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}
_LOCK = threading.Lock()


def clean_card(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "calls_user": str(raw.get("calls_user") or "")[:30],
        "self_ref": str(raw.get("self_ref") or "")[:20],
        "speech_style": str(raw.get("speech_style") or "")[:200],
        "phrases": [str(x)[:60] for x in (raw.get("phrases") or [])][:8],
        "topics": [str(x)[:30] for x in (raw.get("topics") or [])][:8],
    }


def persona_card(space: Space, llm: Any, texts: list[str]) -> dict[str, Any]:
    """페르소나 카드. LLM을 쓸 수 없거나 실패하면 빈 카드(말투 근거 녹음만으로 답한다)."""
    with _LOCK:
        cached = _CACHE.get(space.id)
        if cached and cached[0] == space.index_version:
            return cached[1]
    card: dict[str, Any] = {}
    if getattr(llm, "persona_card", None) and llm.name != "mock" and texts:
        try:
            card = clean_card(llm.persona_card(space.person_name, texts[:80]))
        except ProviderError as e:
            log.warning("persona_failed provider=%s code=%s", llm.name, e.code)
    if card:
        with _LOCK:
            _CACHE[space.id] = (space.index_version, card)
        log.info("persona_built space=%s phrases=%d", space.id, len(card["phrases"]))
    return card


def drop_persona(space_id: str) -> None:
    with _LOCK:
        _CACHE.pop(space_id, None)
