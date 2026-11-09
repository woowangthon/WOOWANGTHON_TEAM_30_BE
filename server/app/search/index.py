"""공간별 검색 색인.

- 대화에 쓰는 클립(그 사람 목소리로 확인된 것)만 색인한다.
- 공간의 index_version이 바뀌면(자막 고침, 포함/제외, 삭제, 새 클립) 다시 만든다.
- 점수 = BM25(단어) + 0.3·BM25(글자 2-gram) + 태그 일치 + (있으면) 임베딩 유사도
- confidence(0~1) = 질문 낱말·태그 중 얼마나 맞았는지. 기준보다 낮으면 '딱 맞는 녹음은 없어요'.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.ai.llm import Candidate
from app.schemas import LLMIntent
from app.search.bm25 import BM25
from app.search.lexicon import analyze, normalize_dialect
from app.search.tokenizer import BIGRAM_PREFIX, bigrams, get_tokenizer

_CACHE: dict[str, tuple[int, str, SpaceIndex]] = {}
_LOCK = threading.Lock()

W_EXPAND = 0.55
W_TAG = 1.3
W_GRAM = 0.3
W_EMB = 4.0


@dataclass
class ClipDoc:
    clip_id: str
    text: str
    tokens: list[str]
    date: str | None = None
    source: str = ""
    tags: list[str] = field(default_factory=list)
    question: str | None = None
    embedding: list[float] | None = None


def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SpaceIndex:
    def __init__(self, docs: list[ClipDoc]):
        self.docs = docs
        words = [[t for t in d.tokens if not t.startswith(BIGRAM_PREFIX)] for d in docs]
        grams = [[t for t in d.tokens if t.startswith(BIGRAM_PREFIX)] for d in docs]
        self.words = BM25(words)
        self.grams = BM25(grams)
        self.word_sets = [set(w) for w in words]
        self.gram_sets = [set(g) for g in grams]
        n = max(1, len(docs))
        self.max_idf = math.log(1 + (n + 0.5) / 0.5)

    def idf(self, term: str) -> float:
        return self.words.idf.get(term, self.max_idf)

    def _unit_matched(self, i: int, unit: str) -> bool:
        if unit in self.word_sets[i]:
            return True
        if unit.startswith("tag:"):
            return False
        grams = bigrams(unit)
        if not grams:
            return False
        hit = sum(1 for g in grams if g in self.gram_sets[i])
        return hit / len(grams) >= 0.5 and hit >= 1

    def search(
        self, query: str, intent: LLMIntent, k: int = 20, query_vec: list[float] | None = None
    ) -> list[Candidate]:
        if not self.docs:
            return []
        tok = get_tokenizer()
        norm = normalize_dialect(query)
        base_words: list[str] = []
        for t in tok.tokenize(query) + tok.tokenize(norm):
            if not t.startswith(BIGRAM_PREFIX) and t not in base_words:
                base_words.append(t)
        query_grams = [t for t in tok.tokenize(norm) if t.startswith(BIGRAM_PREFIX)]

        analysis = analyze(query)
        expand: list[str] = []
        for e in list(analysis.expand) + list(intent.keywords):
            for t in tok.tokenize(normalize_dialect(e)):
                if not t.startswith(BIGRAM_PREFIX) and t not in base_words and t not in expand:
                    expand.append(t)
        tags = list(dict.fromkeys(list(intent.tags) + analysis.tags))
        tag_terms = [f"tag:{t}" for t in tags]

        weights: dict[str, float] = {}
        for t in base_words:
            weights[t] = max(weights.get(t, 0), 1.0)
        for t in expand:
            weights[t] = max(weights.get(t, 0), W_EXPAND)
        for t in tag_terms:
            weights[t] = max(weights.get(t, 0), W_TAG)

        word_scores = self.words.score(weights)
        gram_scores = self.grams.score(query_grams)

        # confidence: 질문 낱말(원문)과 태그 각각이 얼마나 맞았는지 (idf 가중)
        units = [(u, self.idf(u)) for u in base_words if len(u) >= 1] + [
            (t, min(self.idf(t), self.max_idf) * 0.8) for t in tag_terms
        ]
        total = sum(w for _, w in units) or 1.0

        results: list[Candidate] = []
        for i, d in enumerate(self.docs):
            emb = 0.0
            if query_vec is not None and d.embedding is not None:
                emb = max(0.0, _cos(query_vec, d.embedding) - 0.25)
            score = word_scores[i] + W_GRAM * gram_scores[i] + W_EMB * emb
            if score <= 0:
                continue
            matched_units = [u for u, _ in units if self._unit_matched(i, u)]
            got = sum(w for u, w in units if u in matched_units)
            exp_hit = sum(self.idf(e) for e in expand if e in self.word_sets[i])
            conf = (got + 0.5 * min(exp_hit, total * 0.6)) / total
            if emb > 0:
                conf = max(conf, min(1.0, emb * 2.2))
            results.append(
                Candidate(
                    clip_id=d.clip_id,
                    text=d.text,
                    date=d.date,
                    source=d.source,
                    tags=d.tags,
                    question=d.question,
                    score=round(score, 4),
                    confidence=round(min(conf, 1.0), 3),
                    matched=[u for u in matched_units if not u.startswith("tag:")],
                )
            )
        results.sort(key=lambda c: c.score, reverse=True)
        return results[:k]


def get_space_index(space_id: str, version: int, loader) -> SpaceIndex:
    """loader() -> list[ClipDoc]. 버전이 같으면 캐시를 쓴다."""
    tok_name = get_tokenizer().name
    with _LOCK:
        cached = _CACHE.get(space_id)
        if cached and cached[0] == version and cached[1] == tok_name:
            return cached[2]
    idx = SpaceIndex(loader())
    with _LOCK:
        _CACHE[space_id] = (version, tok_name, idx)
    return idx


def drop_space_index(space_id: str) -> None:
    with _LOCK:
        _CACHE.pop(space_id, None)
