"""BM25 (Okapi). 공간 하나의 클립 수(수백~수천)에 맞춘 단순 구현."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence


class BM25:
    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.4, b: float = 0.6):
        self.k1 = k1
        self.b = b
        self.n = len(docs)
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avgdl = (sum(self.len) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for c in self.tf:
            df.update(c.keys())
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: Sequence[str] | dict[str, float]) -> list[float]:
        weights = query if isinstance(query, dict) else Counter(query)
        scores = [0.0] * self.n
        if not self.n:
            return scores
        for term, qw in weights.items():
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(term)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avgdl or 1))
                scores[i] += qw * idf * f * (self.k1 + 1) / denom
        return scores
