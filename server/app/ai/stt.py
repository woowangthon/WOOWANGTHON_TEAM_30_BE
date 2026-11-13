"""음성 인식(STT) 어댑터. 결과 형식: [{start, end, text, speaker?, confidence}]"""

from __future__ import annotations

import base64
import json
import logging
import math
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from app.ai.base import ProviderError, api_key
from app.config import FIXTURES_DIR, get_settings
from app.pipeline import media
from app.schemas import TranscriptSegment

log = logging.getLogger("yeoun.stt")

STT_FIXTURE_DIR = FIXTURES_DIR / "stt"
CHUNK_SEC = 600.0


class MockSTT:
    """키 없이 쓰는 STT.

    1) 테스트·데모용 fixture 자막(fixtures/stt/<sha256>.json)이 있으면 그대로 쓴다.
    2) 없으면 무음 구간으로 말소리 구간만 나누고 자막은 비워 둔다
       (사용자가 '목소리 확인' 화면에서 직접 적을 수 있다. 지어낸 자막을 넣지 않는다).
    """

    name = "mock"
    live = False

    def transcribe(self, wav: Path, *, sha256: str | None, duration: float) -> list[TranscriptSegment]:
        if sha256:
            path = STT_FIXTURE_DIR / f"{sha256}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return [TranscriptSegment(**seg) for seg in data["segments"]]
        regions = media.detect_speech(wav, duration)
        if not regions and duration > 0.5:
            regions = [(0.0, duration)]
        return [TranscriptSegment(start=s, end=e, text="", speaker=None, confidence=None) for s, e in regions]


class OpenAISTT:
    """OpenAI 음성 인식 (whisper-1, verbose_json 구간 타임스탬프). 긴 파일은 10분씩 나눠 보낸다."""

    name = "openai"
    live = True

    def __init__(self, key: str):
        self.key = key
        self.model = get_settings().openai_stt_model

    def _call(self, path: Path) -> dict:
        s = get_settings()
        with path.open("rb") as f:
            try:
                r = httpx.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.key}"},
                    data={
                        "model": self.model,
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment",
                        "language": "ko",
                    },
                    files={"file": (path.name, f, "audio/mpeg")},
                    timeout=s.stt_timeout_sec,
                )
            except httpx.TimeoutException as e:
                raise ProviderError("timeout") from e
            except httpx.HTTPError as e:
                raise ProviderError("http_error", type(e).__name__) from e
        if r.status_code != 200:
            raise ProviderError("http_error", f"status={r.status_code}")
        return r.json()

    def transcribe(self, wav: Path, *, sha256: str | None, duration: float) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        n = max(1, math.ceil(duration / CHUNK_SEC))
        with tempfile.TemporaryDirectory(prefix="yeoun-stt-") as tmp:
            for i in range(n):
                offset = i * CHUNK_SEC
                part = Path(tmp) / f"part{i}.mp3"
                media.encode_for_upload(
                    wav, part, start=offset if n > 1 else None, duration=CHUNK_SEC if n > 1 else None
                )
                data = self._call(part)
                for seg in data.get("segments") or []:
                    text = (seg.get("text") or "").strip()
                    if not text or float(seg.get("no_speech_prob") or 0) > 0.8:
                        continue
                    conf = seg.get("avg_logprob")
                    segments.append(
                        TranscriptSegment(
                            start=offset + float(seg["start"]),
                            end=offset + float(seg["end"]),
                            text=text,
                            confidence=round(math.exp(float(conf)), 3) if conf is not None else None,
                        )
                    )
        return segments

    def transcribe_short(self, path: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="yeoun-stt-") as tmp:
            part = Path(tmp) / "voice.mp3"
            media.encode_for_upload(path, part)
            return (self._call(part).get("text") or "").strip()


class GeminiSTT:
    """Gemini 음성 인식. 오디오를 inline으로 보내고 구간별 JSON을 받는다 (타임스탬프는 근사값)."""

    name = "gemini"
    live = True

    SCHEMA = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "start": {"type": "NUMBER"},
                "end": {"type": "NUMBER"},
                "text": {"type": "STRING"},
                "speaker": {"type": "STRING"},
            },
            "required": ["start", "end", "text"],
        },
    }

    def __init__(self, key: str):
        self.key = key
        self.model = get_settings().gemini_model

    def _generate(self, audio: bytes, prompt: str, schema: dict | None) -> str:
        s = get_settings()
        body: dict = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": "audio/mp3", "data": base64.b64encode(audio).decode()}},
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0},
        }
        if schema:
            body["generationConfig"].update(
                {"responseMimeType": "application/json", "responseSchema": schema}
            )
        try:
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.key},
                json=body,
                timeout=s.stt_timeout_sec,
            )
        except httpx.HTTPError as e:
            raise ProviderError("http_error", type(e).__name__) from e
        if r.status_code != 200:
            raise ProviderError("http_error", f"status={r.status_code}")
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise ProviderError("bad_output") from e

    def transcribe(self, wav: Path, *, sha256: str | None, duration: float) -> list[TranscriptSegment]:
        prompt = (
            "이 한국어 녹음을 받아 적어 주세요. 문장 단위로 나누고 각 구간의 시작·끝(초, 소수 가능)과 "
            "말한 사람(A, B, …)을 붙이세요. 들리지 않는 말은 지어내지 말고 빼세요."
        )
        segments: list[TranscriptSegment] = []
        n = max(1, math.ceil(duration / CHUNK_SEC))
        with tempfile.TemporaryDirectory(prefix="yeoun-stt-") as tmp:
            for i in range(n):
                offset = i * CHUNK_SEC
                part = Path(tmp) / f"part{i}.mp3"
                media.encode_for_upload(
                    wav, part, start=offset if n > 1 else None, duration=CHUNK_SEC if n > 1 else None
                )
                raw = self._generate(part.read_bytes(), prompt, self.SCHEMA)
                try:
                    items = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise ProviderError("bad_output") from e
                for it in items:
                    try:
                        seg = TranscriptSegment(
                            start=offset + float(it["start"]),
                            end=offset + float(it["end"]),
                            text=str(it["text"]).strip(),
                            speaker=it.get("speaker"),
                        )
                    except (KeyError, ValueError, TypeError):
                        continue
                    if seg.text and seg.end > seg.start:
                        segments.append(seg)
        return segments

    def transcribe_short(self, path: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="yeoun-stt-") as tmp:
            part = Path(tmp) / "voice.mp3"
            media.encode_for_upload(path, part)
            return self._generate(
                part.read_bytes(), "이 한국어 음성을 그대로 받아 적어 주세요. 글자만 답하세요.", None
            ).strip()


NOVA_CHUNK_SEC = 3600.0  # mp3 48kbps 1시간 ≈ 21.6MB (게이트웨이 본문 상한 25MB, 오디오 상한 120분)


class NovaSTT:
    """충북대 NOVA API Gateway 받아쓰기 (Soniox stt-async).

    작업 시작(POST, multipart) → operation_id → 상태 폴링(GET) 두 단계다. 화자 분리 결과가 함께 오므로
    구간마다 speaker를 붙여 돌려주고, 화자 분리 단계(NovaDiarizer)는 그 값을 그대로 쓴다.
    1시간이 넘는 파일만 나눠 보낸다(나눈 조각끼리는 화자 번호가 이어지지 않을 수 있다).
    """

    name = "nova"
    live = True

    def __init__(self, key: str):
        s = get_settings()
        self.key = key
        self.model = s.nova_stt_model
        self.url = s.nova_base_url.rstrip("/") + "/audio/transcriptions/"
        self.poll_sec = max(1.0, s.nova_stt_poll_sec)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    def _start(self, path: Path, *, diarize: bool) -> str:
        s = get_settings()
        with path.open("rb") as f:
            try:
                r = httpx.post(
                    self.url,
                    headers=self._headers(),
                    data={
                        "model": self.model,
                        "language_hints": "ko",
                        "enable_speaker_diarization": "true" if diarize else "false",
                    },
                    files={"file": (path.name, f, "audio/mpeg")},
                    timeout=s.stt_timeout_sec,
                )
            except httpx.TimeoutException as e:
                raise ProviderError("timeout") from e
            except httpx.HTTPError as e:
                raise ProviderError("http_error", type(e).__name__) from e
        if r.status_code not in (200, 201, 202):
            raise ProviderError("http_error", f"status={r.status_code}")
        try:
            op = str(r.json()["operation_id"])
        except (KeyError, TypeError, ValueError) as e:
            raise ProviderError("bad_output", "no operation_id") from e
        log.info("nova_stt_started credits=%s", r.headers.get("X-Credits-Charged"))
        return op

    def _wait(self, op: str) -> dict:
        s = get_settings()
        url = f"{self.url}{quote(op, safe='')}/"
        deadline = time.monotonic() + s.stt_timeout_sec
        while True:
            time.sleep(self.poll_sec)
            try:
                r = httpx.get(url, headers=self._headers(), timeout=30.0)
            except httpx.HTTPError:
                r = None
            if r is not None and r.status_code == 200:
                try:
                    data = r.json()
                except ValueError as e:
                    raise ProviderError("bad_output") from e
                status = data.get("status")
                if status == "completed":
                    return data
                if status == "failed":
                    raise ProviderError("http_error", "transcription_failed")
            elif r is not None and r.status_code not in (429, 500, 502, 503, 504):
                raise ProviderError("http_error", f"status={r.status_code}")
            if time.monotonic() > deadline:
                raise ProviderError("timeout")

    @staticmethod
    def _speaker(label: object) -> str | None:
        text = str(label or "").strip()
        if not text or text.lower() == "speaker unknown":
            return None
        return text.replace("Speaker ", "S")

    def transcribe(self, wav: Path, *, sha256: str | None, duration: float) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        n = max(1, math.ceil(duration / NOVA_CHUNK_SEC))
        with tempfile.TemporaryDirectory(prefix="yeoun-stt-") as tmp:
            for i in range(n):
                offset = i * NOVA_CHUNK_SEC
                part = Path(tmp) / f"part{i}.mp3"
                media.encode_for_upload(
                    wav, part, start=offset if n > 1 else None, duration=NOVA_CHUNK_SEC if n > 1 else None
                )
                data = self._wait(self._start(part, diarize=True))
                for seg in data.get("segments") or []:
                    text = (seg.get("text") or "").strip()
                    try:
                        start = offset + float(seg["start_ms"]) / 1000
                        end = offset + float(seg["end_ms"]) / 1000
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not text or end <= start:
                        continue
                    segments.append(
                        TranscriptSegment(start=start, end=end, text=text, speaker=self._speaker(seg.get("speaker")))
                    )
        return segments

    def transcribe_short(self, path: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="yeoun-stt-") as tmp:
            part = Path(tmp) / "voice.mp3"
            media.encode_for_upload(path, part)
            return (self._wait(self._start(part, diarize=False)).get("text") or "").strip()


def build(name: str):
    if name == "nova":
        key = api_key("nova")
        if not key:
            raise ProviderError("not_configured")
        return NovaSTT(key)
    if name == "openai":
        key = api_key("openai")
        if not key:
            raise ProviderError("not_configured")
        return OpenAISTT(key)
    if name == "gemini":
        key = api_key("gemini")
        if not key:
            raise ProviderError("not_configured")
        return GeminiSTT(key)
    return MockSTT()
