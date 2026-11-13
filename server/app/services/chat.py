"""원본 기반 대화.

① 위기 신호 검사 → ② 의도·키워드 파악 → ③ BM25(+임베딩)로 후보 20개 → ④ LLM이 최대 3개 고르고 이유
→ ⑤ 클립 카드(원문 자막·날짜·출처·같은 날 사진) + 짧은 여운 안내.

그 사람의 말은 언제나 DB에 저장된 원본 클립(자막)뿐이다. LLM이 쓴 문장은 '여운 안내'로만 나가고,
후보 밖 ID·지어낸 인용은 guard가 버린다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai import guard, registry
from app.ai.base import ProviderError
from app.ai.embedding import unpack
from app.ai.llm import GUIDE_BY_INTENT, NO_MATCH_GUIDE, Candidate, MockLLM
from app.care.crisis import care_notice, combine, rule_risk
from app.config import get_settings
from app.models import Asset, Clip, Favorite, Space, Speaker
from app.schemas import ChatResponse, GuideMessage, LLMIntent
from app.search.index import ClipDoc, get_space_index
from app.search.query import doc_tokens
from app.search.tokenizer import get_tokenizer
from app.services.assets import ORIGIN_LABELS, clip_cards
from app.services.spaces import included_expr

log = logging.getLogger("yeoun.chat")

# 이 아래면 LLM을 부르지 않고 바로 '딱 맞는 녹음은 없어요' (비용·환각 줄이기)
LLM_FLOOR = 0.12

# 맞는 녹음도, 가까운 추억도 없을 때 (가까운 추억을 놓아두겠다고 약속하지 않는다)
NO_MATCH_ALONE_GUIDE = "딱 맞는 녹음은 없어요."
# 대화에 쓸 녹음이 하나도 없을 때: 목소리를 아직 안 골랐는지, 녹음 자체가 없는지 알려 준다
NO_CLIPS_PENDING_GUIDE = (
    "아직 {person}의 목소리를 고르지 않아서 대화에 쓸 녹음이 없어요. "
    "위 메뉴의 '목소리 확인'에서 {person}의 목소리를 골라 주세요."
)
NO_CLIPS_EMPTY_GUIDE = (
    "아직 대화에 쓸 {person}의 녹음이 없어요. "
    "'자료'에서 통화 녹음이나 음성 메시지를 올리고, '목소리 확인'에서 {person}의 목소리를 골라 주세요."
)


def _no_clips_guide(db: Session, space: Space) -> str:
    pending = db.scalar(
        select(func.count()).select_from(Speaker).where(Speaker.space_id == space.id, Speaker.role == "unknown")
    )
    template = NO_CLIPS_PENDING_GUIDE if pending else NO_CLIPS_EMPTY_GUIDE
    return template.format(person=space.person_name)


def load_docs(db: Session, space_id: str) -> list[ClipDoc]:
    rows = db.execute(
        select(Clip, Asset)
        .join(Asset, Asset.id == Clip.asset_id)
        .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
        .where(
            Clip.space_id == space_id,
            included_expr(),
            or_(func.length(Clip.text) > 0, Asset.question_text.is_not(None)),
        )
        .order_by(Asset.recorded_at.nullslast(), Clip.seq)
    ).all()
    tok_name = get_tokenizer().name
    docs = []
    for clip, asset in rows:
        tokens = clip.tokens
        if clip.tokenizer != tok_name or not tokens:
            tokens = doc_tokens(clip.text, clip.tags or [], asset.question_text)
        docs.append(
            ClipDoc(
                clip_id=clip.id,
                text=clip.text,
                tokens=tokens,
                date=asset.recorded_at.isoformat() if asset.recorded_at else None,
                source=ORIGIN_LABELS.get(asset.origin, "녹음"),
                tags=clip.tags or [],
                question=asset.question_text,
                embedding=unpack(clip.embedding) if clip.embedding else None,
            )
        )
    return docs


@dataclass
class Answer:
    response: ChatResponse
    candidates: list[Candidate]


def _parse_intent(llm, message: str) -> tuple[LLMIntent, str]:
    try:
        raw = llm.parse_intent(message)
        intent = guard.validate_intent(raw)
        if intent is not None:
            return intent, llm.name
    except ProviderError as e:
        log.warning("intent_fallback provider=%s code=%s", llm.name, e.code)
    intent = guard.validate_intent(MockLLM().parse_intent(message))
    assert intent is not None
    return intent, "mock"


def _nearby(
    db: Session, space: Space, intent: LLMIntent, user_id: str | None, exclude: set[str]
) -> list[str]:
    """맞는 녹음이 없을 때 보여 줄 가까운 추억: 같은 태그 → 즐겨찾기 → 최근 녹음."""
    base = (
        select(Clip.id, Clip.tags)
        .join(Asset, Asset.id == Clip.asset_id)
        .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
        .where(
            Clip.space_id == space.id,
            included_expr(),
            or_(func.length(Clip.text) > 0, Asset.question_text.is_not(None)),
        )
    )
    rows = db.execute(base.order_by(Asset.recorded_at.desc().nullslast(), Clip.seq)).all()
    picked: list[str] = []
    if intent.tags:
        scored = sorted(
            ((len(set(tags or []) & set(intent.tags)), cid) for cid, tags in rows if cid not in exclude),
            key=lambda x: -x[0],
        )
        picked += [cid for score, cid in scored if score > 0][:2]
    if user_id and len(picked) < 3:
        favs = db.scalars(
            select(Favorite.clip_id)
            .join(Clip, Clip.id == Favorite.clip_id)
            .where(Favorite.user_id == user_id, Clip.space_id == space.id)
            .order_by(Favorite.created_at.desc())
        ).all()
        picked += [f for f in favs if f not in picked and f not in exclude][: 3 - len(picked)]
    for cid, _ in rows:
        if len(picked) >= 3:
            break
        if cid not in picked and cid not in exclude:
            picked.append(cid)
    return picked[:3]


def answer(db: Session, space: Space, message: str, *, user_id: str | None, consent: bool) -> Answer:
    s = get_settings()
    message = message.strip()

    # ① 위기 신호 (규칙)
    rule_level = rule_risk(message)

    # ② 의도·키워드
    llm, _res = registry.build("llm", consent=consent, is_sample=space.is_sample)
    intent, intent_by = _parse_intent(llm, message)
    level = combine(rule_level, intent.risk if (s.care_llm_classifier and intent_by != "mock") else None)

    # ③ 후보 검색
    index = get_space_index(space.id, space.index_version, lambda: load_docs(db, space.id))
    query_vec = None
    if any(d.embedding is not None for d in index.docs):
        embedder, _ = registry.build("embedding", consent=consent, is_sample=space.is_sample)
        if embedder.live:
            try:
                vecs = embedder.embed([message])
                query_vec = vecs[0] if vecs else None
            except ProviderError as e:
                log.warning("query_embedding_failed code=%s", e.code)
    candidates = index.search(message, intent, k=20, query_vec=query_vec)

    # ④ 고르기
    picker = "mock"
    checked = guard.CheckedSelection(no_good_match=True)
    best = max((c.confidence for c in candidates), default=0.0)
    if candidates and (best >= LLM_FLOOR or query_vec is not None):
        try:
            raw = llm.select(message, intent, candidates, space.person_name)
            checked = guard.validate_selection(raw, candidates)
            picker = llm.name
            if not checked.valid:
                raise ProviderError("bad_output")
        except ProviderError as e:
            if llm.name != "mock":
                log.warning("select_fallback provider=%s code=%s", llm.name, e.code)
            checked = guard.validate_selection(
                MockLLM().select(message, intent, candidates, space.person_name), candidates
            )
            picker = "mock"

    matched = bool(checked.picks)
    clip_ids = [cid for cid, _ in checked.picks]
    by_id = {c.clip_id: c for c in candidates}
    reasons: dict[str, str | None] = {}
    for cid, reason in checked.picks:
        reasons[cid] = reason or _fallback_reason(by_id.get(cid))
    cards = clip_cards(db, space.id, clip_ids, user_id, reasons)

    if matched:
        guide_text = checked.guide or GUIDE_BY_INTENT.get(intent.intent, GUIDE_BY_INTENT["general"])
        nearby_cards = []
    elif not index.docs:
        guide_text = _no_clips_guide(db, space)
        nearby_cards = []
    else:
        nearby_ids = _nearby(db, space, intent, user_id, set())
        nearby_cards = clip_cards(
            db, space.id, nearby_ids, user_id, {cid: "가까운 추억" for cid in nearby_ids}
        )
        guide_text = NO_MATCH_GUIDE if nearby_cards else NO_MATCH_ALONE_GUIDE

    if level == "high":
        guide_text = (
            "먼저 마음을 살펴 주세요. 아래에 " + space.person_name + "의 녹음도 함께 놓아둘게요."
            if (matched or nearby_cards)
            else "먼저 마음을 살펴 주세요."
        )

    response = ChatResponse(
        care=care_notice(level),
        guide=GuideMessage(text=guide_text),
        clips=cards,
        matched=matched,
        nearby=nearby_cards,
        intent=intent.intent,  # type: ignore[arg-type]
        keywords=intent.keywords,
        picker=picker,
    )
    log.info(
        "chat space=%s matched=%s picks=%d candidates=%d care=%s picker=%s",
        space.id,
        matched,
        len(cards),
        len(candidates),
        level,
        picker,
    )
    return Answer(response=response, candidates=candidates)


def _fallback_reason(c: Candidate | None) -> str | None:
    if c is None:
        return None
    if c.question:
        return "미리 남기기 질문에 답하신 녹음이에요."
    if c.date:
        return f"{c.date[:4]}년 {int(c.date[5:7])}월 {c.source}이에요."
    return None
