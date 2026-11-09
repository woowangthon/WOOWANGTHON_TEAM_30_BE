"""질문을 검색어로 바꾸기 (키워드·확장어·태그)."""

from __future__ import annotations

from app.search.lexicon import normalize_dialect
from app.search.tokenizer import BIGRAM_PREFIX, LiteTokenizer, get_tokenizer

_lite = LiteTokenizer()


def word_tokens(text: str) -> list[str]:
    """2-gram을 뺀 단어 토큰."""
    return [t for t in get_tokenizer().tokenize(text) if not t.startswith(BIGRAM_PREFIX)]


def keywords_of(text: str) -> list[str]:
    """사람이 읽을 수 있는 키워드 (중복 제거, 순서 유지)."""
    out: list[str] = []
    for t in word_tokens(normalize_dialect(text)):
        if len(t) >= 1 and t not in out:
            out.append(t)
    return out


def doc_tokens(text: str, tags: list[str], question: str | None = None) -> list[str]:
    """클립 하나의 색인 토큰: 원문 + 사투리 정규화 사본 + 태그 + (미리 남기기) 질문."""
    tok = get_tokenizer()
    tokens = tok.tokenize(text)
    norm = normalize_dialect(text)
    if norm != text:
        extra = tok.tokenize(norm)
        seen = set(tokens)
        tokens += [t for t in extra if t not in seen]
    tokens += [f"tag:{t}" for t in tags]
    if question:
        # 질문과 연결된 답은 질문 낱말로도 찾을 수 있게 (두 번 넣어 가중치를 준다)
        q = tok.tokenize(normalize_dialect(question))
        tokens += q + [t for t in q if not t.startswith(BIGRAM_PREFIX)]
    return tokens
