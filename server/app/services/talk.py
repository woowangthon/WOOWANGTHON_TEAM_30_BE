"""기억 대화: 그 사람과 메신저처럼 대화하기.

녹음 전체에서 뽑은 페르소나 카드(services/persona.py)와 메시지마다 찾은 관련 녹음(memories)으로
그 사람처럼 답장 하나를 만든다.

답장을 고르는 순서:
    ① 위기 신호(규칙) → 그 사람 목소리를 멈추고 "잠깐 멈출게요…" + 상담 번호 (crisis)
    ② 금지 주제(유언·돈·그 사람의 판단·의료·법률) → 여운 안내 (guide)
    ①' 답장을 만드는 LLM이 함께 판단한 위험도가 규칙보다 높으면 그쪽을 따른다(낮추지는 못함)
    ③ 원본 녹음 하나가 그대로 답이 되면 → 그 녹음을 답장으로 (original, 자막은 DB 원문 그대로)
    ④ 아니면 → 페르소나와 근거 녹음으로 만든 답장 (generated, 'AI가 만든 말' + 근거)
       근거가 없거나 거절이면, 또는 경험·사실·조언을 묻는 말인데 관련 녹음이 근거에 없으면 → 여운 안내 (guide)

AI가 만든 답(generated)은 반드시 generated_reply() 한 곳을 거쳐 나간다.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import guard, registry
from app.ai.base import ProviderError
from app.ai.llm import MockLLM
from app.care.crisis import care_notice, combine, rule_risk
from app.config import get_settings
from app.models import Asset, Clip, Space, Speaker
from app.schemas import CareNotice, TalkResponse, TalkTurn
from app.search.index import get_space_index
from app.services.assets import ORIGIN_LABELS, clip_cards
from app.services.chat import _no_clips_guide, load_docs
from app.services.persona import persona_card
from app.services.spaces import included_expr

log = logging.getLogger("yeoun.talk")

MEMORY_COUNT = 12
# 검색 일치도가 이 값 이상인 녹음만 '이번 메시지와 관련된 녹음'으로 본다.
# 샘플 공간 기준: 골든 질문의 최고 일치도는 0.33 이상, 녹음에 없는 질문은 0.1 이하.
RELATED_MIN = 0.25
CRISIS_TEXT = "잠깐 멈출게요. 지금 마음이 어떠세요?"
FORBIDDEN_TEXT = (
    "이 이야기는 {person}께서 남기신 말로 대신할 수 없어서, 여운이 대신 답하지 않을게요. "
    "가족과 함께 이야기 나눠 보시면 좋겠어요."
)
NO_ANSWER_TEXT = "그 이야기는 {person}의 녹음에 없어서, 말을 지어내지 않을게요. 녹음에 남아 있는 기억을 물어봐 주세요."
NO_AI_TEXT = "지금은 답장을 만들 수 없어서, 녹음에 있는 말만 들려드릴 수 있어요."

# 그 사람이 남긴 말로 대신할 수 없는 주제 (요청과 만든 답 양쪽에 건다)
FORBIDDEN = re.compile(
    r"유언|유산|상속|재산|계좌|비밀번호|보증|대출|빌려|송금|돈\s?(좀|을|이|보내|줘|주)|"
    r"용서|원망|미워했|사과해|진단|처방|수술|소송|고소|법적"
)


# 그 사람을 부르며 시작하는 말 ("엄마, …", "여보세요, 할머니?") — 그 사람이 한 말이 아니라 가족이 그분에게 한 말
ADDRESSED = re.compile(
    r"^\s*(여보세요[\s,.~!?]*)?(엄마|어머니|어머님|할머니|할매|할미|아빠|아버지|아버님|할아버지|할배)\s*[,.!?~…]"
)


def addressed_to_person(text: str) -> bool:
    """목소리 확인이 틀렸을 때를 대비한 안전장치: 그분을 부르는 말은 그분의 말로 쓰지 않는다."""
    return bool(ADDRESSED.match(text or ""))


def person_clips(db: Session, space_id: str) -> list[tuple[Clip, Asset]]:
    """'그 사람'으로 확인된, 자막이 있는 클립 (날짜순). 그분을 부르는 말은 뺀다."""
    rows = db.execute(
        select(Clip, Asset)
        .join(Asset, Asset.id == Clip.asset_id)
        .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
        .where(Clip.space_id == space_id, included_expr(), func.length(Clip.text) > 0)
        .order_by(Asset.recorded_at.nullslast(), Asset.created_at, Clip.seq)
    ).all()
    return [(c, a) for c, a in rows if not addressed_to_person(c.text)]


def clip_for_prompt(clip: Clip, asset: Asset) -> dict[str, Any]:
    return {
        "clip_id": clip.id,
        "date": asset.recorded_at.isoformat() if asset.recorded_at else None,
        "source": ORIGIN_LABELS.get(asset.origin, "녹음"),
        "tags": clip.tags or [],
        "text": clip.text[:240],
    }


def llm_risk(raw: dict[str, Any]) -> str | None:
    r = raw.get("risk")
    return r if r in ("none", "watch", "high") else None


def decide_generated(
    raw: dict[str, Any], allowed: set[str], related: set[str]
) -> tuple[str, list[str]] | None:
    """LLM이 만든 답을 내보낼지 정한다. 내보내면 (글, 근거 clip_id 1~3개), 아니면 None(여운 안내).

    - 거절·빈 글·근거 없음·금지 표현이면 버린다.
    - 그분의 경험·사실·정보·조언을 묻는 말에 답한 것(kind가 'feeling'이 아님)은
      이번 메시지와 내용이 관련된 녹음(related)이 근거에 하나 이상 있어야 한다. 없으면 지어낸 답으로 보고 버린다.
    - 관련 녹음을 근거 목록 앞에 둔다.
    """
    text = str(raw.get("text") or "").strip()[:300]
    src = [i for i in dict.fromkeys(str(x) for x in (raw.get("source_clip_ids") or [])) if i in allowed][:3]
    if raw.get("refuse") or not text or not src or FORBIDDEN.search(text):
        return None
    if raw.get("kind") != "feeling" and not (set(src) & related):
        return None
    src.sort(key=lambda i: i not in related)
    return text, src


def _guide(text: str, care: CareNotice | None, provider: str) -> TalkResponse:
    return TalkResponse(mode="guide", text=text, clips=[], sources=[], care=care, provider=provider)


def original_reply(
    db: Session, space: Space, clip: Clip, *, care: CareNotice | None, provider: str, user_id: str | None
) -> TalkResponse:
    """원본 녹음 하나를 그대로 답장으로 (자막은 DB 원문, LLM이 옮긴 글자는 쓰지 않는다)."""
    return TalkResponse(
        mode="original",
        text=clip.text,
        clips=clip_cards(db, space.id, [clip.id], user_id, with_photos=False),
        sources=[],
        care=care,
        provider=provider,
    )


def generated_reply(
    db: Session,
    space: Space,
    text: str,
    source_ids: list[str],
    *,
    care: CareNotice | None,
    provider: str,
    user_id: str | None,
) -> TalkResponse:
    """AI가 만든 답장(mode=generated)이 나가는 유일한 자리.

    text: 페르소나·근거 녹음으로 만든 말(이미 검증됨), source_ids: 근거 녹음 clip_id 1~3개.
    음성 합성을 붙인다면 이 함수 안에서 한 줄로 부른다(지금은 합성하지 않는다).
    """
    return TalkResponse(
        mode="generated",
        text=text,
        clips=[],
        sources=clip_cards(db, space.id, source_ids, user_id, with_photos=False),
        care=care,
        provider=provider,
    )


def talk(
    db: Session,
    space: Space,
    message: str,
    history: list[TalkTurn],
    *,
    user_id: str | None,
    consent: bool,
) -> TalkResponse:
    message = message.strip()
    person = space.person_name

    # ① 위기 신호
    level = rule_risk(message)
    if level == "high":
        log.info("talk space=%s mode=crisis", space.id)
        return TalkResponse(mode="crisis", text=CRISIS_TEXT, clips=[], sources=[], care=care_notice("high"), provider="rule")
    care = care_notice(level)

    # ② 금지 주제
    if FORBIDDEN.search(message):
        return _guide(FORBIDDEN_TEXT.format(person=person), care, "rule")

    rows = person_clips(db, space.id)
    if not rows:
        return _guide(_no_clips_guide(db, space), care, "rule")
    by_id = {c.id: (c, a) for c, a in rows}

    # 관련 녹음 찾기 (그 사람 목소리만). 모자라면 최근 녹음으로 말투 근거를 채운다
    intent = guard.validate_intent(MockLLM().parse_intent(message))
    assert intent is not None
    index = get_space_index(space.id, space.index_version, lambda: load_docs(db, space.id))
    hits = [h for h in index.search(message, intent, k=MEMORY_COUNT) if h.clip_id in by_id]
    picked = [h.clip_id for h in hits]
    for c, _ in reversed(rows):
        if len(picked) >= MEMORY_COUNT:
            break
        if c.id not in picked:
            picked.append(c.id)
    memories = [clip_for_prompt(*by_id[i]) for i in picked]

    related = {h.clip_id for h in hits if h.confidence >= RELATED_MIN}
    for m in memories:
        m["related"] = m["clip_id"] in related

    llm, _ = registry.build("llm", consent=consent, is_sample=space.is_sample)
    if llm.name == "mock" or not getattr(llm, "talk_reply", None):
        # AI 없이: ③ 딱 맞는 원본만 들려준다
        good = [h for h in hits if h.confidence >= get_settings().match_threshold]
        if good:
            return original_reply(db, space, by_id[good[0].clip_id][0], care=care, provider="search", user_id=user_id)
        return _guide(NO_AI_TEXT, care, "mock")

    card = persona_card(space, llm, [c.text[:160] for c, _ in rows])
    past = [{"role": t.role, "text": t.text[:300]} for t in history[-8:]]
    try:
        raw = llm.talk_reply(person, card, memories, past, message)
    except ProviderError as e:
        log.warning("talk_llm_failed provider=%s code=%s", llm.name, e.code)
        return _guide(NO_AI_TEXT, care, "mock")
    if not isinstance(raw, dict):
        return _guide(NO_ANSWER_TEXT.format(person=person), care, llm.name)

    # ①' LLM 위험도: 규칙이 놓친 돌려 말한 위기 표현. 규칙보다 높일 때만 따른다(낮추지 못함)
    level = combine(level, llm_risk(raw))
    if level == "high":
        log.info("talk space=%s mode=crisis by=llm", space.id)
        return TalkResponse(mode="crisis", text=CRISIS_TEXT, clips=[], sources=[], care=care_notice("high"), provider=llm.name)
    care = care_notice(level)

    allowed = set(picked)
    # ③ 원본 녹음이 그대로 답이 되는 경우
    use = str(raw.get("use_clip_id") or "").strip()
    if use in allowed:
        log.info("talk space=%s mode=original", space.id)
        return original_reply(db, space, by_id[use][0], care=care, provider=llm.name, user_id=user_id)

    # ④ AI가 만든 답 (근거 없음·거절·금지 표현·관련 녹음 없는 사실 답이면 안내)
    decided = decide_generated(raw, allowed, related)
    if decided is None:
        log.info("talk space=%s mode=guide refused=%s kind=%s", space.id, bool(raw.get("refuse")), raw.get("kind"))
        return _guide(NO_ANSWER_TEXT.format(person=person), care, llm.name)
    text, src = decided
    log.info("talk space=%s mode=generated kind=%s sources=%d", space.id, raw.get("kind"), len(src))
    return generated_reply(db, space, text, src, care=care, provider=llm.name, user_id=user_id)
