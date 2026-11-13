"""AI 공급자 고르기와 데이터 정책.

- auto: 키가 있는 실제 공급자를 순서대로 고르고, 없으면 mock/none.
- 입력을 학습에 쓰는 무료 등급(예: Gemini 무료)은
  · production: 실제 사용자 자료에 쓰지 않는다 (blocked_by_policy)
  · staging: 공간 소유자가 안내를 보고 동의한 경우에만 쓴다 (needs_consent)
  · development/test: 쓸 수 있다
  샘플(가상 인물) 자료는 정책과 상관없이 쓸 수 있다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.ai import diarization, embedding, llm, stt
from app.ai.base import ProviderError, ProviderMeta, api_key, meta_for
from app.config import get_settings

log = logging.getLogger("yeoun.registry")

FUNCTIONS = ("stt", "diarization", "llm", "embedding")
AUTO_ORDER = {
    "stt": ["nova", "openai", "gemini"],
    "diarization": ["nova", "openai"],
    "llm": ["nova", "anthropic", "openai", "gemini"],
    "embedding": ["nova", "openai", "gemini"],
}
FALLBACK = {"stt": "mock", "diarization": "none", "llm": "mock", "embedding": "none"}
LOCAL = {"mock", "none", "replay"}
_BUILDERS = {
    "stt": stt.build,
    "diarization": diarization.build,
    "llm": llm.build,
    "embedding": embedding.build,
}

STATUS_NOTES = {
    "not_configured": "API 키가 없어 기본 방식으로 처리해요.",
    "blocked_by_policy": "입력을 학습에 쓰는 무료 등급이라 실제 사용자 자료에는 쓰지 않아요.",
    "needs_consent": "입력을 학습에 쓰는 무료 등급이에요. 설정에서 동의해야 쓸 수 있어요.",
    "model_missing": "모델 파일이 없어 기본 방식으로 처리해요.",
}


@dataclass
class Resolution:
    function: str
    requested: str
    name: str
    status: str
    note: str | None
    meta: ProviderMeta
    blocked: list[tuple[str, str]]  # (공급자, 상태) — 설정 화면 안내용


def resolve(function: str, *, consent: bool = False, is_sample: bool = False) -> Resolution:
    s = get_settings()
    requested = getattr(s, f"{function}_provider")
    order = AUTO_ORDER[function] if requested == "auto" else [requested]
    blocked: list[tuple[str, str]] = []
    for name in order:
        if name in LOCAL:
            return Resolution(function, requested, name, "active", None, meta_for(function, name), blocked)
        if not api_key(name):
            if requested != "auto":
                blocked.append((name, "not_configured"))
            continue
        meta = meta_for(function, name)
        if meta.trains_on_input and not is_sample:
            if s.env == "production":
                blocked.append((name, "blocked_by_policy"))
                continue
            if s.env == "staging" and not consent:
                blocked.append((name, "needs_consent"))
                continue
        return Resolution(function, requested, name, "active", None, meta, blocked)
    fb = FALLBACK[function]
    note = STATUS_NOTES[blocked[-1][1]] if blocked else None
    return Resolution(function, requested, fb, "active", note, meta_for(function, fb), blocked)


def build(function: str, *, consent: bool = False, is_sample: bool = False) -> tuple[Any, Resolution]:
    res = resolve(function, consent=consent, is_sample=is_sample)
    try:
        return _BUILDERS[function](res.name), res
    except ProviderError as e:
        log.warning("provider_build_failed function=%s provider=%s code=%s", function, res.name, e.code)
        fb = FALLBACK[function]
        res = Resolution(
            function,
            res.requested,
            fb,
            "active",
            STATUS_NOTES.get(e.code),
            meta_for(function, fb),
            res.blocked,
        )
        return _BUILDERS[function](fb), res


def live_stt_available() -> bool:
    """실제 음성 인식을 쓸 수 있는지 (동의가 필요한 공급자는 제외)."""
    return resolve("stt", consent=False).name not in LOCAL


def describe_all(*, consent: bool) -> list[dict]:
    """설정 화면: 기능별로 지금 쓰는 공급자와 막힌 공급자."""
    rows: list[dict] = []
    for fn in FUNCTIONS:
        res = resolve(fn, consent=consent)
        rows.append({"meta": res.meta, "status": "active", "note": res.note})
        for name, status in res.blocked:
            try:
                meta = meta_for(fn, name)
            except ValueError:
                continue
            rows.append({"meta": meta, "status": status, "note": STATUS_NOTES.get(status)})
    return rows
