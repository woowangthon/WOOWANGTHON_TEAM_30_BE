"""목소리가 들리는 기억책과 기억 통화.

책: 그 사람으로 확인된 클립(자막)을 LLM이 장·문단으로 정리한다. 문단마다 근거 클립을 달고,
    목록 밖 clip_id는 버리며, 근거가 없거나 따옴표 인용이 원본 자막과 다르면 grounded=false로 표시한다.
    LLM을 쓸 수 없으면 해별로 원본 한 마디씩 그대로 인용하는 규칙 기반 책을 만든다.

기억 통화(책의 한 장에서만 열림) 답을 고르는 순서:
    ① 위기 신호 → 고인 목소리 멈춤, "잠깐 멈출게요. 지금 마음이 어떠세요?" + 상담 번호 (crisis)
    ② 금지 주제(유언·돈·고인의 판단·의료·법률) → 여운 안내로 전환 (guide)
    ③ 이 장의 원본 녹음에 맞는 말이 있으면 → 원본 재생 (original)
    ④ 그 밖에는 → 이 장의 근거 녹음과 말투로 짧은 답 생성, 'AI 생성' 표시 + 근거 클립 (generated)
       근거가 없거나 LLM이 거절하면 여운 안내 (guide)
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import guard, registry
from app.ai.base import ProviderError
from app.ai.llm import MockLLM
from app.care.crisis import care_notice, rule_risk
from app.config import get_settings
from app.errors import ApiError
from app.models import Asset, Book, Clip, Space, Speaker
from app.schemas import Book as BookOut
from app.schemas import BookChapter, BookParagraph, CallResponse, CallTurn
from app.search.index import ClipDoc, SpaceIndex
from app.search.query import doc_tokens
from app.services.assets import ORIGIN_LABELS, clip_cards
from app.services.spaces import included_expr

log = logging.getLogger("yeoun.book")

MAX_SOURCE_CLIPS = 150
CRISIS_TEXT = "잠깐 멈출게요. 지금 마음이 어떠세요?"
ORIGINAL_TEXT = "이 기억에 대해 {person}께서 실제로 하신 말씀이에요."
FORBIDDEN_TEXT = (
    "이 이야기는 {person}께서 남기신 말로 대신할 수 없어서, 여운이 대신 답하지 않을게요. "
    "가족과 함께 이야기 나눠 보시면 좋겠어요."
)
NO_EVIDENCE_TEXT = (
    "이 기억에는 그 이야기에 대한 녹음이 없어서, 말을 지어내지 않을게요. 이 장에 나온 장면을 물어봐 주세요."
)
NO_AI_TEXT = "지금은 AI 답 만들기를 쓸 수 없어서, 녹음에 있는 말만 들려드릴 수 있어요."

# 고인이 남긴 말로 대신할 수 없는 주제 (요청과 생성된 답 양쪽에 건다)
_FORBIDDEN = re.compile(
    r"유언|유산|상속|재산|계좌|비밀번호|보증|대출|빌려|송금|돈\s?(좀|을|이|보내|줘|주)|"
    r"용서|원망|미워했|사과해|진단|처방|수술|소송|고소|법적"
)
_QUOTE = re.compile(r"[“\"]([^”\"]{4,})[”\"]")


# ---------------------------------------------------------------- 원본 클립


def _person_clips(db: Session, space_id: str, ids: list[str] | None = None) -> list[tuple[Clip, Asset]]:
    stmt = (
        select(Clip, Asset)
        .join(Asset, Asset.id == Clip.asset_id)
        .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
        .where(Clip.space_id == space_id, included_expr(), func.length(Clip.text) > 0)
    )
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(Clip.id.in_(ids))
    stmt = stmt.order_by(Asset.recorded_at.nullslast(), Asset.created_at, Clip.seq)
    return list(db.execute(stmt).all())


def _clip_for_prompt(clip: Clip, asset: Asset) -> dict[str, Any]:
    return {
        "clip_id": clip.id,
        "date": asset.recorded_at.isoformat() if asset.recorded_at else None,
        "source": ORIGIN_LABELS.get(asset.origin, "녹음"),
        "tags": clip.tags or [],
        "text": clip.text[:240],
    }


def source_clip_count(db: Session, space_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Clip)
            .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
            .where(Clip.space_id == space_id, included_expr(), func.length(Clip.text) > 0)
        )
        or 0
    )


# ---------------------------------------------------------------- 책 만들기


def _short_id() -> str:
    return uuid.uuid4().hex[:10]


def _quotes_ok(text: str, clip_texts: list[str]) -> bool:
    """문단 속 따옴표 인용이 근거 자막에 그대로 있는지 (지어낸 인용 막기)."""
    joined = " ".join(clip_texts)
    for q in _QUOTE.findall(text):
        if q.strip().rstrip(".!?…") not in joined:
            return False
    return True


def check_draft(raw: Any, texts: dict[str, str]) -> list[dict[str, Any]]:
    """LLM 초안 검증: 목록 밖 clip_id 버림, 빈 문단 버림, 근거 없음·인용 불일치는 grounded=false."""
    chapters: list[dict[str, Any]] = []
    if not isinstance(raw, dict):
        return chapters
    for ch in (raw.get("chapters") or [])[:8]:
        if not isinstance(ch, dict):
            continue
        paragraphs = []
        for p in (ch.get("paragraphs") or [])[:8]:
            if not isinstance(p, dict):
                continue
            text = str(p.get("text") or "").strip()[:600]
            if not text:
                continue
            ids = [i for i in dict.fromkeys(str(x) for x in (p.get("clip_ids") or [])) if i in texts][:6]
            grounded = bool(ids) and _quotes_ok(text, [texts[i] for i in ids])
            paragraphs.append({"id": _short_id(), "text": text, "clip_ids": ids, "grounded": grounded, "edited": False})
        if paragraphs:
            title = str(ch.get("title") or "").strip()[:40] or "기억"
            period = str(ch.get("period") or "").strip()[:30] or None
            chapters.append({"id": _short_id(), "title": title, "period": period, "paragraphs": paragraphs})
    return chapters


def generate_book(db: Session, space: Space, *, consent: bool) -> Book:
    rows = _person_clips(db, space.id)[:MAX_SOURCE_CLIPS]
    if not rows:
        raise ApiError(400, "book_no_clips")
    clips = [_clip_for_prompt(c, a) for c, a in rows]
    texts = {c.id: c.text for c, _ in rows}

    llm, _ = registry.build("llm", consent=consent, is_sample=space.is_sample)
    chapters: list[dict[str, Any]] = []
    title = ""
    by = "mock"
    if getattr(llm, "write_book", None) and llm.name != "mock":
        try:
            raw = llm.write_book(space.person_name, clips)
            chapters = check_draft(raw, texts)
            title = str((raw or {}).get("title") or "").strip()[:80] if isinstance(raw, dict) else ""
            by = llm.name
        except ProviderError as e:
            log.warning("book_llm_failed provider=%s code=%s", llm.name, e.code)
    if not chapters:
        raw = MockLLM().write_book(space.person_name, clips)
        chapters = check_draft(raw, texts)
        title = raw["title"]
        by = "mock"

    book = db.scalar(select(Book).where(Book.space_id == space.id))
    if book is None:
        book = Book(space_id=space.id)
        db.add(book)
    book.title = title or f"{space.person_name}의 목소리가 들리는 책"
    book.chapters = chapters
    book.status = "draft"
    book.approved_at = None
    book.generated_by = by
    db.flush()
    n = sum(len(ch["paragraphs"]) for ch in chapters)
    g = sum(p["grounded"] for ch in chapters for p in ch["paragraphs"])
    log.info("book_generated space=%s by=%s chapters=%d paragraphs=%d grounded=%d", space.id, by, len(chapters), n, g)
    return book


MAX_CHAPTERS = 30


def _mock_story(space: Space, prompt: str, rows: list[tuple[Clip, Asset]]) -> dict[str, Any]:
    """LLM 없이: 요청과 맞는 녹음(BM25)을 찾아 원본 한 마디씩 그대로 인용한다."""
    intent = guard.validate_intent(MockLLM().parse_intent(prompt))
    assert intent is not None
    docs = [
        ClipDoc(
            clip_id=c.id,
            text=c.text,
            tokens=doc_tokens(c.text, c.tags or [], a.question_text),
            date=a.recorded_at.isoformat() if a.recorded_at else None,
            source=ORIGIN_LABELS.get(a.origin, "녹음"),
            tags=c.tags or [],
            question=a.question_text,
        )
        for c, a in rows
    ]
    # 기억 요청은 '…하던 기억'처럼 길어서 대화보다 낮은 기준을 쓴다
    hits = [h for h in SpaceIndex(docs).search(prompt, intent, k=4) if h.confidence >= 0.1]
    by_id = {c.id: (c, a) for c, a in rows}
    paragraphs = []
    for h in hits:
        c, a = by_id[h.clip_id]
        when = f"{a.recorded_at.year}년 {a.recorded_at.month}월" if a.recorded_at else "언젠가"
        paragraphs.append(
            {"text": f"{when}, {space.person_name}께서 이렇게 말씀하셨어요. “{c.text}”", "clip_ids": [c.id]}
        )
    return {"found": bool(paragraphs), "title": prompt[:40], "period": "", "paragraphs": paragraphs}


def add_story(db: Session, space: Space, prompt: str, *, consent: bool) -> Book:
    """가족이 적은 기억 하나로 이야기 한 장을 써서 책 맨 앞에 더한다. 관련 녹음이 없으면 지어내지 않는다."""
    prompt = prompt.strip()
    rows = _person_clips(db, space.id)[:MAX_SOURCE_CLIPS]
    if not rows:
        raise ApiError(400, "book_no_clips")
    texts = {c.id: c.text for c, _ in rows}
    llm, _ = registry.build("llm", consent=consent, is_sample=space.is_sample)
    raw: Any = None
    by = "mock"
    if getattr(llm, "write_story", None) and llm.name != "mock":
        try:
            raw = llm.write_story(space.person_name, prompt, [_clip_for_prompt(c, a) for c, a in rows])
            by = llm.name
        except ProviderError as e:
            log.warning("story_llm_failed provider=%s code=%s", llm.name, e.code)
    if not isinstance(raw, dict):
        raw = _mock_story(space, prompt, rows)
        by = "mock"
    chapters = check_draft({"chapters": [raw]}, texts) if raw.get("found") else []
    if not chapters:
        log.info("story_not_found space=%s by=%s", space.id, by)
        raise ApiError(404, "story_not_found")
    chapter = chapters[0]
    chapter["prompt"] = prompt[:300]

    book = db.scalar(select(Book).where(Book.space_id == space.id))
    if book is None:
        book = Book(space_id=space.id, title=f"{space.person_name}의 목소리가 들리는 책", chapters=[], status="draft")
        db.add(book)
    book.chapters = ([chapter] + list(book.chapters or []))[:MAX_CHAPTERS]
    book.status = "draft"
    book.approved_at = None
    if not book.generated_by:
        book.generated_by = by
    db.flush()
    log.info("story_added space=%s by=%s paragraphs=%d", space.id, by, len(chapter["paragraphs"]))
    return book


def delete_chapter(book: Book, chapter_id: str) -> None:
    kept = [ch for ch in book.chapters if ch.get("id") != chapter_id]
    if len(kept) == len(book.chapters):
        raise ApiError(404, "not_found")
    book.chapters = kept


def book_out(db: Session, space: Space, book: Book | None, *, user_id: str | None, can_edit: bool) -> BookOut:
    count = source_clip_count(db, space.id)
    if book is None:
        return BookOut(exists=False, chapters=[], clips=[], can_edit=can_edit, source_clip_count=count)
    ids = [i for ch in book.chapters for p in ch.get("paragraphs", []) for i in p.get("clip_ids", [])]
    alive = {c.id for c, _ in _person_clips(db, space.id, list(dict.fromkeys(ids)))}
    chapters = []
    total = grounded = 0
    for ch in book.chapters:
        paragraphs = []
        for p in ch.get("paragraphs", []):
            kept = [i for i in p.get("clip_ids", []) if i in alive]
            ok = bool(p.get("grounded")) and bool(kept)
            total += 1
            grounded += ok
            paragraphs.append(
                BookParagraph(id=p["id"], text=p["text"], clip_ids=kept, grounded=ok, edited=bool(p.get("edited")))
            )
        chapters.append(
            BookChapter(id=ch["id"], title=ch["title"], period=ch.get("period"), prompt=ch.get("prompt"), paragraphs=paragraphs)
        )
    order = [i for i in dict.fromkeys(ids) if i in alive]
    return BookOut(
        exists=True,
        status=book.status,  # type: ignore[arg-type]
        title=book.title,
        chapters=chapters,
        clips=clip_cards(db, space.id, order, user_id),
        generated_by=book.generated_by,
        updated_at=book.updated_at,
        grounded_ratio=round(grounded / total, 3) if total else None,
        can_edit=can_edit,
        source_clip_count=count,
    )


def find_paragraph(book: Book, paragraph_id: str) -> dict[str, Any] | None:
    for ch in book.chapters:
        for p in ch.get("paragraphs", []):
            if p.get("id") == paragraph_id:
                return p
    return None


def update_paragraph(db: Session, book: Book, paragraph_id: str, text: str) -> None:
    chapters = [dict(ch, paragraphs=[dict(p) for p in ch.get("paragraphs", [])]) for ch in book.chapters]
    for ch in chapters:
        for p in ch["paragraphs"]:
            if p["id"] == paragraph_id:
                rows = _person_clips(db, book.space_id, p.get("clip_ids") or [])
                p["text"] = text.strip()[:1000]
                p["edited"] = True
                p["grounded"] = bool(rows) and _quotes_ok(p["text"], [c.text for c, _ in rows])
                book.chapters = chapters  # JSONB는 새 객체를 넣어야 바뀐 것으로 본다
                book.status = "draft"
                book.approved_at = None
                return
    raise ApiError(404, "not_found")


# ---------------------------------------------------------------- 기억 통화


def _chapter(book: Book, chapter_id: str) -> dict[str, Any]:
    for ch in book.chapters:
        if ch.get("id") == chapter_id:
            return ch
    raise ApiError(404, "not_found")


def call(
    db: Session,
    space: Space,
    book: Book,
    chapter_id: str,
    message: str,
    history: list[CallTurn],
    *,
    user_id: str | None,
    consent: bool,
) -> CallResponse:
    message = message.strip()
    person = space.person_name
    ch = _chapter(book, chapter_id)

    # ① 위기 신호: 고인 목소리를 멈추고 상담 연결
    level = rule_risk(message)
    if level == "high":
        log.info("call space=%s chapter=%s mode=crisis", space.id, chapter_id)
        return CallResponse(mode="crisis", text=CRISIS_TEXT, clips=[], sources=[], care=care_notice("high"), provider="rule")
    care = care_notice(level)

    # ② 금지 주제
    if _FORBIDDEN.search(message):
        return CallResponse(mode="guide", text=FORBIDDEN_TEXT.format(person=person), clips=[], sources=[], care=care, provider="rule")

    ids = list(dict.fromkeys(i for p in ch.get("paragraphs", []) for i in p.get("clip_ids", [])))
    rows = _person_clips(db, space.id, ids)
    if not rows:
        return CallResponse(mode="guide", text=NO_EVIDENCE_TEXT, clips=[], sources=[], care=care, provider="rule")

    # ③ 원본 우선: 이 장의 녹음 안에서 검색
    intent = guard.validate_intent(MockLLM().parse_intent(message))
    assert intent is not None
    docs = [
        ClipDoc(
            clip_id=c.id,
            text=c.text,
            tokens=doc_tokens(c.text, c.tags or [], a.question_text),
            date=a.recorded_at.isoformat() if a.recorded_at else None,
            source=ORIGIN_LABELS.get(a.origin, "녹음"),
            tags=c.tags or [],
            question=a.question_text,
        )
        for c, a in rows
    ]
    hits = SpaceIndex(docs).search(message, intent, k=5)
    threshold = get_settings().match_threshold
    good = [h.clip_id for h in hits if h.confidence >= threshold][:2]
    if good:
        log.info("call space=%s chapter=%s mode=original picks=%d", space.id, chapter_id, len(good))
        return CallResponse(
            mode="original",
            text=ORIGINAL_TEXT.format(person=person),
            clips=clip_cards(db, space.id, good, user_id, with_photos=False),
            sources=[],
            care=care,
            provider="search",
        )

    # ④ 근거 안에서 생성 (AI 생성 표시)
    llm, _ = registry.build("llm", consent=consent, is_sample=space.is_sample)
    if llm.name == "mock" or not getattr(llm, "call_reply", None):
        return CallResponse(mode="guide", text=NO_AI_TEXT, clips=[], sources=[], care=care, provider="mock")
    evidence = [_clip_for_prompt(c, a) for c, a in rows][:30]
    style_rows = _person_clips(db, space.id)
    style = [c.text[:120] for c, _ in style_rows if c.id not in set(ids)][:8]
    past = [{"role": t.role, "text": t.text[:300]} for t in history[-6:]]
    try:
        raw = llm.call_reply(person, ch.get("title", ""), evidence, style, past, message)
    except ProviderError as e:
        log.warning("call_llm_failed provider=%s code=%s", llm.name, e.code)
        return CallResponse(mode="guide", text=NO_EVIDENCE_TEXT, clips=[], sources=[], care=care, provider="mock")
    allowed = {c.id for c, _ in rows}
    text = str((raw or {}).get("text") or "").strip()[:400] if isinstance(raw, dict) else ""
    src = [i for i in dict.fromkeys(str(x) for x in ((raw or {}).get("source_clip_ids") or [])) if i in allowed][:3] if isinstance(raw, dict) else []
    refused = not isinstance(raw, dict) or bool(raw.get("refuse"))
    if refused or not text or not src or _FORBIDDEN.search(text):
        log.info("call space=%s chapter=%s mode=guide refused=%s sources=%d", space.id, chapter_id, refused, len(src))
        return CallResponse(mode="guide", text=NO_EVIDENCE_TEXT, clips=[], sources=[], care=care, provider=llm.name)
    log.info("call space=%s chapter=%s mode=generated sources=%d", space.id, chapter_id, len(src))
    return CallResponse(
        mode="generated",
        text=text,
        clips=[],
        sources=clip_cards(db, space.id, src, user_id, with_photos=False),
        care=care,
        provider=llm.name,
    )


__all__ = [
    "book_out",
    "call",
    "check_draft",
    "find_paragraph",
    "add_story",
    "delete_chapter",
    "generate_book",
    "source_clip_count",
    "update_paragraph",
]
