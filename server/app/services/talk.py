"""그 사람과 메신저처럼 대화하기 (페르소나 대화).

녹음 전체에서 말하기 특징(페르소나 카드: 호칭·자기 호칭·어미·자주 쓰는 말)을 한 번 뽑아 두고,
메시지마다 관련 녹음(memories)을 찾아 그 사람처럼 답장 하나를 만든다.

답장을 고르는 순서:
    ① 위기 신호 → 그 사람 목소리를 멈추고 "잠깐 멈출게요…" + 상담 번호 (crisis)
    ② 금지 주제(유언·돈·그 사람의 판단·의료·법률) → 여운 안내 (guide)
    ③ 원본 녹음 하나가 그대로 답이 되면 → 그 녹음을 답장으로 (original, 자막은 DB 원문 그대로)
    ④ 아니면 → 페르소나와 근거 녹음으로 만든 답장 (generated, 'AI가 만든 말' + 근거)
       근거가 없거나 거절이면 → 여운 안내 (guide)
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.ai import guard, registry
from app.ai.base import ProviderError
from app.ai.llm import MockLLM
from app.care.crisis import care_notice, rule_risk
from app.config import get_settings
from app.models import Space
from app.schemas import CallResponse, CallTurn
from app.search.index import get_space_index
from app.services.assets import clip_cards
from app.services.book import _FORBIDDEN, CRISIS_TEXT, FORBIDDEN_TEXT, _clip_for_prompt, _person_clips
from app.services.chat import _no_clips_guide, load_docs

log = logging.getLogger("yeoun.talk")

NO_ANSWER_TEXT = "그 이야기는 {person}의 녹음에 없어서, 말을 지어내지 않을게요. 녹음에 남아 있는 기억을 물어봐 주세요."
NO_AI_TEXT = "지금은 답장을 만들 수 없어서, 녹음에 있는 말만 들려드릴 수 있어요."

_PERSONA: dict[str, tuple[int, dict[str, Any]]] = {}
_LOCK = threading.Lock()


def persona_card(space: Space, llm: Any, texts: list[str]) -> dict[str, Any]:
    """녹음이 바뀌지 않았으면(index_version 같음) 만들어 둔 카드를 다시 쓴다."""
    with _LOCK:
        cached = _PERSONA.get(space.id)
        if cached and cached[0] == space.index_version:
            return cached[1]
    card: dict[str, Any] = {}
    if getattr(llm, "persona_card", None) and llm.name != "mock" and texts:
        try:
            raw = llm.persona_card(space.person_name, texts[:80])
            if isinstance(raw, dict):
                card = {
                    "calls_user": str(raw.get("calls_user") or "")[:30],
                    "self_ref": str(raw.get("self_ref") or "")[:20],
                    "speech_style": str(raw.get("speech_style") or "")[:200],
                    "phrases": [str(x)[:60] for x in (raw.get("phrases") or [])][:8],
                    "topics": [str(x)[:30] for x in (raw.get("topics") or [])][:8],
                }
        except ProviderError as e:
            log.warning("persona_failed provider=%s code=%s", llm.name, e.code)
    if card:
        with _LOCK:
            _PERSONA[space.id] = (space.index_version, card)
    return card


def talk(
    db: Session,
    space: Space,
    message: str,
    history: list[CallTurn],
    *,
    user_id: str | None,
    consent: bool,
) -> CallResponse:
    message = message.strip()
    person = space.person_name

    level = rule_risk(message)
    if level == "high":
        log.info("talk space=%s mode=crisis", space.id)
        return CallResponse(mode="crisis", text=CRISIS_TEXT, clips=[], sources=[], care=care_notice("high"), provider="rule")
    care = care_notice(level)

    if _FORBIDDEN.search(message):
        return CallResponse(mode="guide", text=FORBIDDEN_TEXT.format(person=person), clips=[], sources=[], care=care, provider="rule")

    rows = _person_clips(db, space.id)
    if not rows:
        return CallResponse(mode="guide", text=_no_clips_guide(db, space), clips=[], sources=[], care=care, provider="rule")
    by_id = {c.id: (c, a) for c, a in rows}

    # 관련 녹음 찾기 (BM25, 그 사람 목소리만). 모자라면 최근 녹음으로 말투 근거를 채운다
    intent = guard.validate_intent(MockLLM().parse_intent(message))
    assert intent is not None
    index = get_space_index(space.id, space.index_version, lambda: load_docs(db, space.id))
    hits = [h for h in index.search(message, intent, k=12) if h.clip_id in by_id]
    threshold = get_settings().match_threshold
    picked = [h.clip_id for h in hits]
    for c, _ in reversed(rows):
        if len(picked) >= 12:
            break
        if c.id not in picked:
            picked.append(c.id)
    memories = [_clip_for_prompt(*by_id[i]) for i in picked]

    llm, _ = registry.build("llm", consent=consent, is_sample=space.is_sample)
    if llm.name == "mock" or not getattr(llm, "talk_reply", None):
        good = [h for h in hits if h.confidence >= threshold]
        if good:
            return CallResponse(
                mode="original",
                text=by_id[good[0].clip_id][0].text,
                clips=clip_cards(db, space.id, [good[0].clip_id], user_id, with_photos=False),
                sources=[],
                care=care,
                provider="search",
            )
        return CallResponse(mode="guide", text=NO_AI_TEXT, clips=[], sources=[], care=care, provider="mock")

    card = persona_card(space, llm, [c.text[:160] for c, _ in rows])
    past = [{"role": t.role, "text": t.text[:300]} for t in history[-8:]]
    try:
        raw = llm.talk_reply(person, card, memories, past, message)
    except ProviderError as e:
        log.warning("talk_llm_failed provider=%s code=%s", llm.name, e.code)
        return CallResponse(mode="guide", text=NO_AI_TEXT, clips=[], sources=[], care=care, provider="mock")
    if not isinstance(raw, dict):
        return CallResponse(mode="guide", text=NO_ANSWER_TEXT.format(person=person), clips=[], sources=[], care=care, provider=llm.name)

    allowed = set(picked)
    use = str(raw.get("use_clip_id") or "").strip()
    if use in allowed:
        log.info("talk space=%s mode=original", space.id)
        return CallResponse(
            mode="original",
            text=by_id[use][0].text,  # 원본 자막 그대로 (LLM이 옮긴 글자는 쓰지 않는다)
            clips=clip_cards(db, space.id, [use], user_id, with_photos=False),
            sources=[],
            care=care,
            provider=llm.name,
        )
    text = str(raw.get("text") or "").strip()[:300]
    src = [i for i in dict.fromkeys(str(x) for x in (raw.get("source_clip_ids") or [])) if i in allowed][:3]
    if raw.get("refuse") or not text or not src or _FORBIDDEN.search(text):
        log.info("talk space=%s mode=guide refused=%s sources=%d", space.id, bool(raw.get("refuse")), len(src))
        return CallResponse(mode="guide", text=NO_ANSWER_TEXT.format(person=person), clips=[], sources=[], care=care, provider=llm.name)
    log.info("talk space=%s mode=generated sources=%d", space.id, len(src))
    return CallResponse(
        mode="generated",
        text=text,
        clips=[],
        sources=clip_cards(db, space.id, src, user_id, with_photos=False),
        care=care,
        provider=llm.name,
    )
