"""목소리로 화자를 나누지 못한 녹음을 내용으로 나누기.

STT·화자 분리 결과 목소리가 하나뿐인 통화·영상(비슷한 목소리, 한 사람 휴대폰으로만 녹음된 통화, 합성 음성 등)은
'그 사람' 목소리로 고르면 함께 대화한 가족의 말까지 그 사람 말로 쓰이게 된다.
이때 문장 단위로 나눈 뒤 LLM이 내용(호칭·질문과 대답·당부)으로 A/B를 붙인다.
결과는 '목소리 확인'에서 사람이 고르므로, 여기서는 나누기만 하고 누가 누구인지는 정하지 않는다.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.ai.base import ProviderError
from app.schemas import TranscriptSegment

log = logging.getLogger("yeoun.content_split")

_SPLIT = re.compile(r"(?<=[.?!…])\s+")
MAX_SENTENCES = 300


def to_sentences(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """구간을 문장으로 나눈다. 시간은 글자 수에 비례해 나눈다(근사)."""
    out: list[TranscriptSegment] = []
    for seg in segments:
        parts = [p.strip() for p in _SPLIT.split(seg.text.strip()) if p.strip()] if seg.text.strip() else []
        if len(parts) <= 1:
            out.append(seg)
            continue
        total = sum(len(p) for p in parts)
        dur = seg.end - seg.start
        cursor = seg.start
        for p in parts:
            share = dur * len(p) / total
            out.append(
                TranscriptSegment(
                    start=cursor, end=cursor + share, text=p, speaker=seg.speaker, confidence=seg.confidence
                )
            )
            cursor += share
    return out


def split_by_content(segments: list[TranscriptSegment], llm: Any) -> tuple[list[TranscriptSegment], bool]:
    """목소리가 하나로 나온 녹음을 내용으로 두 사람으로 나눈다. 나누지 못하면 (원래 구간, False)."""
    if not getattr(llm, "split_speakers", None) or llm.name == "mock":
        return segments, False
    sentences = to_sentences([s for s in segments if s.text.strip()])
    if len(sentences) < 3 or len(sentences) > MAX_SENTENCES:
        return segments, False
    try:
        raw = llm.split_speakers([s.text[:200] for s in sentences])
    except ProviderError as e:
        log.warning("content_split_failed provider=%s code=%s", llm.name, e.code)
        return segments, False
    labels = raw.get("labels") if isinstance(raw, dict) else None
    if not isinstance(labels, list) or len(labels) != len(sentences) or any(x not in ("A", "B") for x in labels):
        log.warning("content_split_bad_output n=%d", len(sentences))
        return segments, False
    if len(set(labels)) < 2:
        return segments, False  # 한 사람 녹음
    out = [s.model_copy(update={"speaker": "S1" if lab == "A" else "S2"}) for s, lab in zip(sentences, labels, strict=True)]
    log.info("content_split sentences=%d a=%d b=%d", len(out), labels.count("A"), labels.count("B"))
    return out, True
