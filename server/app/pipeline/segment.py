"""STT 구간 → 문장 단위 클립 (2~30초, 앞뒤 여유).

원칙: 클립은 언제나 원본 녹음의 한 구간이다. 자막은 STT 결과를 나누거나 이어 붙일 뿐 고치지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import TranscriptSegment

MIN_LEN = 2.0
MAX_LEN = 30.0
PAD = 0.3
MAX_GAP = 1.5

_SENT_END = re.compile(r"[.?!…]$|[다요죠네라까나지냐노고]\s*[.?!]?$")
_SPLIT = re.compile(r"(?<=[.?!…])\s+")


@dataclass
class ClipSpan:
    start: float
    end: float
    text: str
    speaker: str | None
    confidence: float | None


def _split_long(seg: TranscriptSegment) -> list[TranscriptSegment]:
    dur = seg.end - seg.start
    if dur <= MAX_LEN:
        return [seg]
    parts = [p for p in _SPLIT.split(seg.text.strip()) if p] if seg.text.strip() else []
    if len(parts) <= 1:
        # 문장 경계가 없으면 시간으로 똑같이 나눈다
        n = int(dur // MAX_LEN) + 1
        step = dur / n
        words = seg.text.split()
        per = max(1, len(words) // n) if words else 0
        out = []
        for i in range(n):
            text = " ".join(words[i * per : (i + 1) * per if i < n - 1 else None]) if words else ""
            out.append(
                TranscriptSegment(
                    start=seg.start + i * step,
                    end=seg.start + (i + 1) * step,
                    text=text,
                    speaker=seg.speaker,
                    confidence=seg.confidence,
                )  # fmt: skip
            )
        return out
    total = sum(len(p) for p in parts)
    out = []
    cursor = seg.start
    for p in parts:
        share = dur * len(p) / total
        out.append(
            TranscriptSegment(
                start=cursor, end=cursor + share, text=p, speaker=seg.speaker, confidence=seg.confidence
            )
        )
        cursor += share
    result: list[TranscriptSegment] = []
    for o in out:
        result.extend(_split_long(o) if o.end - o.start > MAX_LEN and o.text != seg.text else [o])
    return result


def make_clips(segments: list[TranscriptSegment], duration: float) -> list[ClipSpan]:
    segs = sorted((s for s in segments if s.end > s.start), key=lambda s: s.start)
    expanded: list[TranscriptSegment] = []
    for s in segs:
        expanded.extend(_split_long(s))

    groups: list[list[TranscriptSegment]] = []
    for s in expanded:
        if groups:
            g = groups[-1]
            last = g[-1]
            g_dur = last.end - g[0].start
            merged_dur = s.end - g[0].start
            same_speaker = last.speaker == s.speaker
            close = s.start - last.end <= MAX_GAP
            # 자막이 없는 구간(규칙 기반 분할)은 30초까지 이어 붙인다
            incomplete = not last.text.strip() or not _SENT_END.search(last.text.strip())
            if same_speaker and close and merged_dur <= MAX_LEN and (g_dur < MIN_LEN or incomplete):
                g.append(s)
                continue
        groups.append([s])

    clips: list[ClipSpan] = []
    for g in groups:
        start = max(0.0, g[0].start - PAD)
        end = min(duration, g[-1].end + PAD) if duration > 0 else g[-1].end + PAD
        if end - start < MIN_LEN:
            # 짧은 말("응", "그래")은 앞뒤를 조금 넓혀 2초를 맞춘다
            missing = MIN_LEN - (end - start)
            start = max(0.0, start - missing / 2)
            end = min(duration if duration > 0 else end + missing, start + MIN_LEN)
        text = " ".join(x.text.strip() for x in g if x.text.strip())
        confs = [x.confidence for x in g if x.confidence is not None]
        clips.append(
            ClipSpan(
                start=round(start, 3),
                end=round(end, 3),
                text=text,
                speaker=g[0].speaker,
                confidence=round(sum(confs) / len(confs), 3) if confs else None,
            )
        )
    return clips
