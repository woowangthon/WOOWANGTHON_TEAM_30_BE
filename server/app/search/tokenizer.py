"""한국어 토크나이저.

- kiwi: kiwipiepy 형태소 분석 (정확, 메모리 약 350MB)
- lite: 규칙 기반 (조사·어미 떼기). 메모리를 거의 쓰지 않아 Render 무료 등급용.

두 방식 모두 '단어 토큰'과 '글자 2-gram 토큰(b: 접두사)'을 함께 낸다.
2-gram은 "된장찌개"와 "찌개", "아파"와 "아픈"처럼 형태가 조금 다른 말을 이어 준다.
"""

from __future__ import annotations

import logging
import re
import threading
from functools import lru_cache
from typing import Protocol

from app.config import get_settings

log = logging.getLogger("yeoun.tokenizer")

HANGUL_RUN = re.compile(r"[가-힣]+|[a-zA-Z]+|\d+")
BIGRAM_PREFIX = "b:"

# 의미가 거의 없는 말 (검색에서 뺀다)
STOPWORDS = {
    "그",
    "이",
    "저",
    "것",
    "거",
    "수",
    "좀",
    "더",
    "또",
    "막",
    "그냥",
    "진짜",
    "정말",
    "너무",
    "많이",
    "아주",
    "그래",
    "그래서",
    "그러니까",
    "근데",
    "그런데",
    "그리고",
    "있",
    "없",
    "하",
    "되",
    "않",
    "같",
    "보",
    "주",
    "나",
    "내",
    "너",
    "니",
    "네",
    "우리",
    "저희",
    "제",
    "뭐",
    "왜",
    "어떻",
    "어떻게",
    "언제",
    "어디",
    "누구",
    "할머니",
    "할아버지",
    "엄마",
    "아빠",
    "어머니",
    "아버지",
    "오늘",
    "요즘",
    "지금",
    "다시",
    "한번",
    "말",
    "얘기",
    "이야기",
    # 부탁·질문 말투 (녹음 내용과 상관없는 말)
    "법",
    "방법",
    "알리",
    "알려",
    "알려줘",
    "들려",
    "들려줘",
    "말해",
    "말해줘",
    "해줘",
    "줘",
    "궁금",
    "뭐였",
    "뭐였지",
    "뭐야",
    "듣",
    "싶",
    "싶다",
    "싶어",
    "돼",
    "될까",
}

# 길이가 긴 것부터 떼어 낸다
JOSA = sorted(
    [
        "에서는",
        "에게서",
        "으로는",
        "이라도",
        "이라서",
        "이라고",
        "한테서",
        "까지는",
        "부터는",
        "에서",
        "에게",
        "한테",
        "께서",
        "으로",
        "이랑",
        "하고",
        "처럼",
        "보다",
        "마저",
        "조차",
        "까지",
        "부터",
        "이나",
        "이든",
        "이란",
        "라고",
        "이고",
        "이야",
        "에는",
        "에도",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "에",
        "의",
        "도",
        "만",
        "로",
        "와",
        "과",
        "랑",
        "야",
        "아",
        "나",
        "요",
    ],
    key=len,
    reverse=True,
)

ENDINGS = sorted(
    [
        "었었어요",
        "았었어요",
        "었습니다",
        "았습니다",
        "겠습니다",
        "하셨어요",
        "셨어요",
        "었어요",
        "았어요",
        "였어요",
        "했어요",
        "해어요",
        "어서요",
        "아서요",
        "는데요",
        "을까요",
        "ㄹ까요",
        "습니다",
        "합니다",
        "입니다",
        "었는데",
        "았는데",
        "었다가",
        "었어",
        "았어",
        "였어",
        "했어",
        "었다",
        "았다",
        "였다",
        "했다",
        "한다",
        "하다",
        "어요",
        "아요",
        "해요",
        "세요",
        "에요",
        "예요",
        "는데",
        "지만",
        "니까",
        "어서",
        "아서",
        "해서",
        "라서",
        "으면",
        "을까",
        "는지",
        "던데",
        "거든",
        "구나",
        "구먼",
        "그라",
        "거라",
        "어라",
        "아라",
        "해라",
        "하고",
        "고",
        "면",
        "다",
        "지",
        "네",
        "죠",
        "냐",
        "니",
        "래",
        "자",
        "게",
        "어",
        "아",
        "해",
        "요",
        "나",
        "라",
        "던",
        "는",
        "은",
        "을",
        "ㄴ",
    ],
    key=len,
    reverse=True,
)


# 한 글자지만 의미가 큰 명사
SHORT_NOUNS = {
    "밥",
    "약",
    "국",
    "떡",
    "꿈",
    "몸",
    "눈",
    "비",
    "돈",
    "집",
    "산",
    "밭",
    "일",
    "옷",
    "잠",
    "술",
    "차",
    "꽃",
    "물",
}


def bigrams(word: str) -> list[str]:
    if len(word) < 2:
        return []
    return [BIGRAM_PREFIX + word[i : i + 2] for i in range(len(word) - 1)]


class Tokenizer(Protocol):
    name: str

    def tokenize(self, text: str) -> list[str]: ...
    def units(self, text: str) -> list[str]: ...


def _strip(word: str, suffixes: list[str], min_left: int = 1) -> str:
    for suf in suffixes:
        if word.endswith(suf) and len(word) - len(suf) >= min_left:
            return word[: -len(suf)]
    return word


STRONG_ENDINGS = ["다", "요", "어", "아", "고", "지", "네", "죠", "자", "게"]


def lite_stems(word: str) -> list[str]:
    """한 어절에서 조사·어미를 떼어 낸 줄기들. 마지막이 대표 줄기다.

    - 조사를 뗐으면 명사로 보고 어미는 더 떼지 않는다 (할머니가 → 할머니, '할머'가 되지 않게)
    - 두 글자 낱말은 확실한 어미만 뗀다 (노래 → 노래, 먹고 → 먹)
    """
    out = [word]
    s1 = _strip(word, JOSA)
    if s1 != word and (len(s1) >= 2 or s1 in SHORT_NOUNS):
        out.append(s1)
        return out
    endings = STRONG_ENDINGS if len(word) <= 2 else ENDINGS
    s2 = _strip(word, endings)
    if s2 != word:
        out.append(s2)
    return [w for w in out if w]


class LiteTokenizer:
    name = "lite"

    def units(self, text: str) -> list[str]:
        """질문의 뜻을 이루는 대표 줄기들 (일치도 계산용)."""
        out: list[str] = []
        for m in HANGUL_RUN.finditer(text.lower()):
            word = m.group(0)
            if word.isdigit():
                continue
            main = lite_stems(word)[-1]
            if main and main not in STOPWORDS and main not in out:
                out.append(main)
        return out

    def tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for m in HANGUL_RUN.finditer(text.lower()):
            word = m.group(0)
            if word.isdigit():
                if len(word) >= 2:
                    tokens.append(word)
                continue
            stems = lite_stems(word)
            main = stems[-1]
            if main not in STOPWORDS and len(main) >= 1:
                tokens.append(main)
            if word != main and word not in STOPWORDS and len(word) >= 3:
                tokens.append(word)
            tokens.extend(bigrams(word))
        return tokens


class KiwiTokenizer:
    name = "kiwi"
    KEEP = {"NNG", "NNP", "VV", "VA", "XR", "MAG", "SL", "SN", "NR", "VV-R", "VA-R", "VV-I", "VA-I"}

    def __init__(self) -> None:
        from kiwipiepy import Kiwi  # 무거운 모듈 (약 350MB)

        self._kiwi = Kiwi(num_workers=-1, model_type="cong", load_typo_dict=False, load_multi_dict=False)
        self._lock = threading.Lock()

    def units(self, text: str) -> list[str]:
        out: list[str] = []
        for t in self.tokenize(text):
            if not t.startswith(BIGRAM_PREFIX) and t not in out:
                out.append(t)
        return out

    def tokenize(self, text: str) -> list[str]:
        with self._lock:
            toks = self._kiwi.tokenize(text.lower())
        out: list[str] = []
        for t in toks:
            if t.tag not in self.KEEP:
                continue
            form = t.form
            if form in STOPWORDS:
                continue
            if len(form) < 2 and t.tag in ("NNG", "MAG") and form not in SHORT_NOUNS:
                continue
            out.append(form)
            if t.tag in ("NNG", "NNP"):
                out.extend(bigrams(form))
        # 원문 어절 2-gram도 넣어 lite와 비슷한 재현율을 맞춘다
        for m in HANGUL_RUN.finditer(text.lower()):
            w = m.group(0)
            if len(w) >= 3:
                out.extend(bigrams(w))
        return out


_lock = threading.Lock()


@lru_cache
def get_tokenizer() -> Tokenizer:
    choice = get_settings().tokenizer
    if choice in ("kiwi", "auto"):
        with _lock:
            try:
                return KiwiTokenizer()
            except Exception as e:  # kiwipiepy 미설치·모델 없음
                if choice == "kiwi":
                    log.warning("kiwi tokenizer unavailable (%s) — using lite", type(e).__name__)
    return LiteTokenizer()


def reset_tokenizer() -> None:
    get_tokenizer.cache_clear()
