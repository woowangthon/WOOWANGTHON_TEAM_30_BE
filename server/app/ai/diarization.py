"""화자 분리 어댑터.

- none: 화자를 나누지 않는다. 사용자가 '목소리 확인'에서 파일·클립 단위로 직접 고른다.
- mock: STT fixture에 화자 표시가 있으면 그것을 쓴다 (테스트·데모).
- nova: NOVA 받아쓰기(Soniox)가 붙인 화자를 그대로 쓴다 (추가 호출·과금 없음).
- openai: gpt-4o-transcribe-diarize의 화자 구간을 STT 구간에 시간 겹침으로 붙인다.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import httpx

from app.ai.base import ProviderError, api_key
from app.config import get_settings
from app.pipeline import media
from app.schemas import TranscriptSegment

log = logging.getLogger("yeoun.diarization")


class NoDiarizer:
    name = "none"

    def diarize(
        self, wav: Path, segments: list[TranscriptSegment], duration: float
    ) -> tuple[list[TranscriptSegment], bool]:
        return [s.model_copy(update={"speaker": None}) for s in segments], False


class MockDiarizer:
    name = "mock"

    def diarize(
        self, wav: Path, segments: list[TranscriptSegment], duration: float
    ) -> tuple[list[TranscriptSegment], bool]:
        if segments and all(s.speaker for s in segments):
            return segments, True
        return [s.model_copy(update={"speaker": None}) for s in segments], False


def assign_speakers(
    segments: list[TranscriptSegment], turns: list[tuple[float, float, str]]
) -> list[TranscriptSegment]:
    """STT 구간마다 가장 많이 겹치는 화자 구간의 화자를 붙인다."""
    out = []
    for seg in segments:
        best, best_overlap = None, 0.0
        for start, end, spk in turns:
            overlap = min(seg.end, end) - max(seg.start, start)
            if overlap > best_overlap:
                best, best_overlap = spk, overlap
        out.append(seg.model_copy(update={"speaker": best}))
    return out


class OpenAIDiarizer:
    name = "openai"

    def __init__(self, key: str):
        self.key = key
        self.model = get_settings().openai_diarize_model

    def diarize(
        self, wav: Path, segments: list[TranscriptSegment], duration: float
    ) -> tuple[list[TranscriptSegment], bool]:
        s = get_settings()
        with tempfile.TemporaryDirectory(prefix="yeoun-diar-") as tmp:
            part = Path(tmp) / "audio.mp3"
            media.encode_for_upload(wav, part)
            with part.open("rb") as f:
                try:
                    r = httpx.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self.key}"},
                        data={
                            "model": self.model,
                            "response_format": "diarized_json",
                            "chunking_strategy": "auto",
                        },
                        files={"file": ("audio.mp3", f, "audio/mpeg")},
                        timeout=s.stt_timeout_sec,
                    )
                except httpx.HTTPError as e:
                    raise ProviderError("http_error", type(e).__name__) from e
        if r.status_code != 200:
            raise ProviderError("http_error", f"status={r.status_code}")
        turns = []
        for seg in r.json().get("segments") or []:
            try:
                turns.append((float(seg["start"]), float(seg["end"]), str(seg["speaker"])))
            except (KeyError, ValueError, TypeError):
                continue
        if not turns:
            return [x.model_copy(update={"speaker": None}) for x in segments], False
        return assign_speakers(segments, turns), True


class NovaDiarizer:
    """NOVA 받아쓰기(Soniox)가 이미 붙인 화자를 그대로 쓴다. 다른 STT 결과라 화자가 없으면 나누지 않는다."""

    name = "nova"

    def diarize(
        self, wav: Path, segments: list[TranscriptSegment], duration: float
    ) -> tuple[list[TranscriptSegment], bool]:
        if segments and any(s.speaker for s in segments):
            return segments, True
        return [s.model_copy(update={"speaker": None}) for s in segments], False


def build(name: str):
    if name == "nova":
        if not api_key("nova"):
            raise ProviderError("not_configured")
        return NovaDiarizer()
    if name == "openai":
        key = api_key("openai")
        if not key:
            raise ProviderError("not_configured")
        return OpenAIDiarizer(key)
    if name == "mock":
        return MockDiarizer()
    return NoDiarizer()
