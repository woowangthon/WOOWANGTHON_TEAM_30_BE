"""그분 목소리 합성 공급자: fal(실제) / mock(키 없을 때, 테스트·개발용).

synthesize(text, ref_audio, ref_text, model, *, ref_seconds, ref_mime, timeout) -> (audio, mime, 걸린 초)

- 모델(논리 이름 → fal endpoint_id)
    "qwen3-tts"  : Qwen3-TTS 1.7B. 복제(clone-voice) → 합성(text-to-speech) 2단계
    "chatterbox" : Chatterbox Multilingual. 참조 음성 주소를 voice 로 넣는 1단계
- 참조 음성이 3초 미만이거나 길이를 알 수 없으면 호출하지 않고 ProviderError("ref_too_short") 로 거절한다.
- 긴 문장은 문장 단위로 묶어 300자 이하 조각으로 나눠 요청하고, 결과를 이어 붙인다.
- 호출은 큐 방식이다: 제출 → 응답의 status_url 폴링 → response_url 결과 → audio.url 내려받기 → 삭제 API.
  (삭제 API 에 필요한 request_id 는 큐 제출 응답에서 얻는다.)
- 개인정보: 모든 fal API 요청에 X-Fal-Store-IO: 0 과 X-Fal-Object-Lifecycle-Preference 를 넣는다.
  참조 음성은 fal CDN 에 올리지 않고 data 주소로 요청 본문에 직접 싣는다.
  끝나면(실패·시간 초과 포함) 생긴 request_id 마다 결과 파일 삭제 API 를 부른다. 끝나지 않은 요청은 먼저 취소한다.
  삭제 실패는 예외로 올리지 않고 상태 코드만 로그에 남긴다.
- 로그·오류 detail 에 문장·자막·파일명·키·주소(서명이 붙을 수 있음)를 남기지 않는다.

출처는 상수마다 주석으로 단다. "미확인"은 공식 문서에서 확인하지 못한 것이다.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import re
import time
import wave
from typing import Any

import httpx

from app.ai.base import ProviderError

log = logging.getLogger("yeoun.voice.provider")

ENV_FAL_KEY = "YEOUN_FAL_API_KEY"

# --- fal 주소 ------------------------------------------------------------------
# 큐 제출: POST https://queue.fal.run/<endpoint_id>. 상태·결과·취소 주소는 제출 응답이 준 것을 그대로 쓴다.
# 출처: https://fal.ai/docs/model-apis/model-endpoints/queue
# 하위 경로가 있는 endpoint_id 를 제출 주소에 그대로 쓰는 것은 문서 예시 기준이며 실제 호출로는 미확인.
FAL_QUEUE_BASE = "https://queue.fal.run/"
# 결과 파일 삭제: DELETE https://api.fal.ai/v1/models/requests/{request_id}/payloads
# 출처: https://fal.ai/docs/platform-apis/v1/models/requests/payloads
FAL_DELETE_URL = "https://api.fal.ai/v1/models/requests/{request_id}/payloads"

# --- 모델 ----------------------------------------------------------------------
# 출처: https://fal.ai/models/fal-ai/qwen-3-tts/clone-voice/1.7b/api
# (fal 페이지는 "Qwen3-TTS [1.7B]"라고만 적고 "Base" 체크포인트 이름은 밝히지 않는다: 미확인)
QWEN_CLONE_ENDPOINT = "fal-ai/qwen-3-tts/clone-voice/1.7b"
# 출처: https://fal.ai/models/fal-ai/qwen-3-tts/text-to-speech/1.7b/llms.txt
QWEN_TTS_ENDPOINT = "fal-ai/qwen-3-tts/text-to-speech/1.7b"
# 출처: 같은 페이지의 language enum (Auto, English, ..., Korean, ...)
QWEN_LANGUAGE = "Korean"
# 출처: https://fal.ai/models/fal-ai/chatterbox/text-to-speech/multilingual/api
CHATTERBOX_ENDPOINT = "fal-ai/chatterbox/text-to-speech/multilingual"
# 출처: 같은 페이지의 custom_audio_language enum (..., korean, ...)
CHATTERBOX_LANGUAGE = "korean"

MODEL_QWEN = "qwen3-tts"
MODEL_CHATTERBOX = "chatterbox"
MODELS = {MODEL_QWEN: QWEN_TTS_ENDPOINT, MODEL_CHATTERBOX: CHATTERBOX_ENDPOINT}

# --- 길이 ----------------------------------------------------------------------
MIN_REF_SEC = 3.0  # 참조 음성 최소 길이(여운 기준, ref.py 와 같음)
# Chatterbox text 최대 300자 (출처: https://fal.ai/models/fal-ai/chatterbox/text-to-speech/multilingual/api).
# Qwen 의 text 글자 수 제한은 미확인 → 같은 상한을 보수적으로 쓴다.
MAX_CHUNK_CHARS = 300

# --- 개인정보 헤더 ---------------------------------------------------------------
# 요청 기록의 JSON 입출력 저장 끄기. CDN 파일에는 적용되지 않는다. 적용 엔드포인트 범위는 미확인.
# 출처: https://fal.ai/docs/documentation/model-apis/common-parameters ,
#       https://fal.ai/docs/documentation/serverless/data-retention
STORE_IO_HEADER = ("X-Fal-Store-IO", "0")
# 생성 파일(CDN) 보관 기간(초). 문서 예시값 3600. 가능한 최소값은 미확인(더 짧게 할 수 있는지 미확인).
# 출처: https://fal.ai/docs/documentation/model-apis/media-expiration
OBJECT_LIFECYCLE_SEC = 3600
LIFECYCLE_HEADER = "X-Fal-Object-Lifecycle-Preference"
# 처리 시작 전 대기 제한(초, 만료 시 504). 출처: https://fal.ai/docs/model-apis/model-endpoints/queue
START_TIMEOUT_HEADER = "X-Fal-Request-Start-Timeout"

# --- 시간 제한 -------------------------------------------------------------------
DEFAULT_TIMEOUT_SEC = 60.0  # synthesize 전체 상한 기본값(reply.py 는 남은 시간을 넘긴다)
HTTP_TIMEOUT_SEC = 15.0  # HTTP 요청 하나의 상한(남은 시간이 더 짧으면 그만큼)
CLEANUP_TIMEOUT_SEC = 5.0  # 취소·삭제 요청 하나의 상한(전체 상한이 지난 뒤에도 정리는 시도한다)
POLL_INTERVAL_SEC = 0.5  # 상태 폴링 간격

_sleep = time.sleep  # 테스트에서 바꿔 끼운다


# =============================================================================
# 공통 도우미


def fal_key() -> str | None:
    v = os.environ.get(ENV_FAL_KEY, "").strip()
    return v or None


def provider_name() -> str:
    return "fal" if fal_key() else "mock"


def sniff_mime(data: bytes) -> str | None:
    """파일 앞부분 서명으로 형식을 판별한다(WAV/MPEG 만)."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    return None


def _norm_mime(m: Any) -> str | None:
    if not isinstance(m, str):
        return None
    m = m.split(";", 1)[0].strip().lower()
    if m in ("audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"):
        return "audio/wav"
    if m in ("audio/mpeg", "audio/mp3", "audio/mpeg3", "audio/x-mpeg"):
        return "audio/mpeg"
    return None


def wav_seconds(data: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except Exception:
        return None


_SENT_END = re.compile(r"(?<=[.!?。！？…~])\s+|\n+")


def split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """문장 단위로 끊고, 이어서 limit 글자 이하 조각으로 묶는다. 한 문장이 limit 보다 길면 쉼표·공백·글자 순으로 자른다."""
    sentences = [s.strip() for s in _SENT_END.split(text or "") if s and s.strip()]
    pieces: list[str] = []
    for s in sentences:
        while len(s) > limit:
            cut = max(s.rfind(",", 0, limit), s.rfind("，", 0, limit), s.rfind(" ", 0, limit))
            cut = cut + 1 if cut > 0 else limit
            pieces.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            pieces.append(s)
    chunks: list[str] = []
    for p in pieces:
        if chunks and len(chunks[-1]) + 1 + len(p) <= limit:
            chunks[-1] = chunks[-1] + " " + p
        else:
            chunks.append(p)
    return chunks


def join_audio(parts: list[tuple[bytes, str]]) -> tuple[bytes, str]:
    """조각 결과를 잇는다. 모두 WAV → wave 로 합침, 모두 MPEG → 프레임 잇기, 섞였거나 모르면 bad_output."""
    if not parts:
        raise ProviderError("bad_output", "no audio")
    mimes = {m for _, m in parts}
    if len(mimes) != 1:
        raise ProviderError("bad_output", "mixed formats")
    mime = mimes.pop()
    if len(parts) == 1:
        return parts[0][0], mime
    if mime == "audio/mpeg":
        from app.voice.reply import join_mp3

        return join_mp3([p for p, _ in parts]), mime
    if mime == "audio/wav":
        out = io.BytesIO()
        params = None
        try:
            with wave.open(out, "wb") as w:
                for data, _ in parts:
                    with wave.open(io.BytesIO(data), "rb") as r:
                        p = (r.getnchannels(), r.getsampwidth(), r.getframerate())
                        if params is None:
                            params = p
                            w.setnchannels(p[0])
                            w.setsampwidth(p[1])
                            w.setframerate(p[2])
                        elif p != params:
                            raise ProviderError("bad_output", "wav params differ")
                        w.writeframes(r.readframes(r.getnframes()))
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError("bad_output", "wav join failed") from e
        return out.getvalue(), mime
    raise ProviderError("bad_output", "unknown format")


def silent_wav(seconds: float = 0.5, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return out.getvalue()


# =============================================================================
# 입구


def synthesize(
    text: str,
    ref_audio: bytes,
    ref_text: str,
    model: str,
    *,
    ref_seconds: float | None = None,
    ref_mime: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> tuple[bytes, str, float]:
    """그분 목소리로 text 를 합성한다. 실패는 ProviderError(code) 로 올린다."""
    started = time.monotonic()
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("bad_input", "empty text")
    if not isinstance(ref_audio, (bytes, bytearray)) or not ref_audio:
        raise ProviderError("bad_input", "empty reference")
    ref_audio = bytes(ref_audio)
    if model not in MODELS:
        raise ProviderError("bad_input", "unknown model")
    mime = _norm_mime(ref_mime) or sniff_mime(ref_audio)
    if mime is None:
        raise ProviderError("bad_input", "unknown reference format")
    secs = ref_seconds
    if secs is None and mime == "audio/wav":
        secs = wav_seconds(ref_audio)
    try:
        secs_f = float(secs) if secs is not None else math.nan
    except (TypeError, ValueError):
        secs_f = math.nan
    if math.isnan(secs_f):
        raise ProviderError("ref_too_short", "reference length unknown")
    if secs_f < MIN_REF_SEC:
        raise ProviderError("ref_too_short", f"reference {secs_f:.1f}s < {MIN_REF_SEC:.0f}s")
    chunks = split_text(text.strip())
    if not chunks:
        raise ProviderError("bad_input", "empty text")
    key = fal_key()
    if key is None:
        audio, out_mime = silent_wav(), "audio/wav"
    else:
        job = _FalJob(key, started + max(0.0, float(timeout)))
        try:
            audio, out_mime = job.run(
                model, chunks, ref_audio, mime, ref_text if isinstance(ref_text, str) else ""
            )
        finally:
            job.cleanup()
    return audio, out_mime, time.monotonic() - started


# =============================================================================
# fal 큐 호출


class _FalJob:
    def __init__(self, key: str, deadline: float):
        self.key = key
        self.deadline = deadline
        self.requests: list[dict[str, Any]] = []  # {"id", "cancel_url", "done"}

    # --- 헤더·HTTP ---
    def headers(self) -> dict[str, str]:
        rem = max(1, math.ceil(self.deadline - time.monotonic()))
        return {
            "Authorization": f"Key {self.key}",
            STORE_IO_HEADER[0]: STORE_IO_HEADER[1],
            LIFECYCLE_HEADER: json.dumps({"expiration_duration_seconds": OBJECT_LIFECYCLE_SEC}),
            START_TIMEOUT_HEADER: str(rem),
        }

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise ProviderError("timeout")
        return left

    def http(self, method: str, url: str, *, json_body: Any = None, auth: bool = True) -> httpx.Response:
        t = min(HTTP_TIMEOUT_SEC, self.remaining())
        try:
            return httpx.request(
                method, url, headers=self.headers() if auth else None, json=json_body, timeout=t
            )
        except httpx.TimeoutException as e:
            raise ProviderError("timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("http_error", type(e).__name__) from e

    # --- 큐 ---
    def submit(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        r = self.http("POST", FAL_QUEUE_BASE + endpoint, json_body=body)
        if r.status_code not in (200, 201, 202):
            raise ProviderError("http_error", f"submit status={r.status_code}")
        try:
            data = r.json()
            req = {
                "id": str(data["request_id"]),
                "status_url": str(data["status_url"]),
                "response_url": str(data["response_url"]),
                "cancel_url": str(data.get("cancel_url") or ""),
                "done": False,
            }
        except (KeyError, TypeError, ValueError) as e:
            raise ProviderError("bad_output", "submit response") from e
        self.requests.append(req)
        return req

    def wait(self, req: dict[str, Any]) -> dict[str, Any]:
        while True:
            r = self.http("GET", req["status_url"])
            if r.status_code not in (200, 202):
                raise ProviderError("http_error", f"status status={r.status_code}")
            try:
                st = r.json()
            except ValueError as e:
                raise ProviderError("bad_output", "status response") from e
            if not isinstance(st, dict):
                raise ProviderError("bad_output", "status response")
            if st.get("error"):
                raise ProviderError("http_error", f"error_type={str(st.get('error_type') or '')[:40]}")
            status = st.get("status")
            if status == "COMPLETED":
                break
            if status not in ("IN_QUEUE", "IN_PROGRESS"):
                raise ProviderError("bad_output", "unknown status")
            _sleep(min(POLL_INTERVAL_SEC, self.remaining()))
        r = self.http("GET", req["response_url"])
        req["done"] = True
        if r.status_code != 200:
            raise ProviderError("http_error", f"result status={r.status_code}")
        try:
            out = r.json()
        except ValueError as e:
            raise ProviderError("bad_output", "result response") from e
        if not isinstance(out, dict):
            raise ProviderError("bad_output", "result response")
        if out.get("error"):
            raise ProviderError("http_error", f"error_type={str(out.get('error_type') or '')[:40]}")
        return out

    def call(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.wait(self.submit(endpoint, body))

    def download(self, file: Any) -> tuple[bytes, str]:
        if not isinstance(file, dict) or not isinstance(file.get("url"), str) or not file["url"]:
            raise ProviderError("bad_output", "no audio url")
        # CDN 파일 주소에는 키를 보내지 않는다
        r = self.http("GET", file["url"], auth=False)
        if r.status_code != 200 or not r.content:
            raise ProviderError("http_error", f"download status={r.status_code}")
        data = r.content
        mime = (
            _norm_mime(file.get("content_type"))
            or _norm_mime(r.headers.get("content-type"))
            or sniff_mime(data)
        )
        if mime is None:
            raise ProviderError("bad_output", "unknown audio format")
        return data, mime

    # --- 모델 ---
    def run(
        self, model: str, chunks: list[str], ref_audio: bytes, ref_mime: str, ref_text: str
    ) -> tuple[bytes, str]:
        # 참조 음성은 CDN 에 올리지 않고 data 주소로 직접 싣는다.
        # 출처: 두 모델 API 페이지 Files 절 "You can pass a Base64 data URI as a file input." (크기 제한 미확인)
        data_uri = f"data:{ref_mime};base64," + base64.b64encode(ref_audio).decode("ascii")
        ref_text = ref_text.strip()
        parts: list[tuple[bytes, str]] = []
        if model == MODEL_QWEN:
            # 1단계 복제. 입력: audio_url(필수), reference_text(선택). enable_safety_checker 는 기본값 그대로.
            clone_body: dict[str, Any] = {"audio_url": data_uri}
            if ref_text:
                clone_body["reference_text"] = ref_text
            emb = self.call(QWEN_CLONE_ENDPOINT, clone_body).get("speaker_embedding")
            if not isinstance(emb, dict) or not isinstance(emb.get("url"), str) or not emb["url"]:
                raise ProviderError("bad_output", "no speaker embedding")
            # 2단계 합성. 입력: text, language, speaker_voice_embedding_file_url, reference_text(선택).
            # voice 는 임베딩이 있으면 무시되므로 보내지 않는다. 나머지 생성 설정은 기본값 그대로.
            for chunk in chunks:
                body: dict[str, Any] = {
                    "text": chunk,
                    "language": QWEN_LANGUAGE,
                    "speaker_voice_embedding_file_url": emb["url"],
                }
                if ref_text:
                    body["reference_text"] = ref_text
                parts.append(self.download(self.call(QWEN_TTS_ENDPOINT, body).get("audio")))
        else:
            # 입력: text(최대 300자), voice(참조 음성 주소), custom_audio_language. 참조 자막 필드는 없다.
            for chunk in chunks:
                body = {"text": chunk, "voice": data_uri, "custom_audio_language": CHATTERBOX_LANGUAGE}
                parts.append(self.download(self.call(CHATTERBOX_ENDPOINT, body).get("audio")))
        audio, mime = join_audio(parts)
        log.info("fal_voice ok model=%s chunks=%d requests=%d", model, len(chunks), len(self.requests))
        return audio, mime

    # --- 정리 ---
    def _cleanup_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Key {self.key}",
            STORE_IO_HEADER[0]: STORE_IO_HEADER[1],
        }

    def cleanup(self) -> None:
        """끝나지 않은 요청은 취소하고, 모든 request_id 의 결과 파일을 삭제한다. 예외를 올리지 않는다."""
        for req in self.requests:
            if not req.get("done") and req.get("cancel_url"):
                try:
                    r = httpx.request(
                        "PUT", req["cancel_url"], headers=self._cleanup_headers(), timeout=CLEANUP_TIMEOUT_SEC
                    )
                    if r.status_code >= 300:
                        log.warning("fal_cancel_failed status=%s", r.status_code)
                except Exception as e:
                    log.warning("fal_cancel_failed error=%s", type(e).__name__)
            try:
                r = httpx.request(
                    "DELETE",
                    FAL_DELETE_URL.format(request_id=req["id"]),
                    headers=self._cleanup_headers(),
                    timeout=CLEANUP_TIMEOUT_SEC,
                )
                if r.status_code != 200:
                    # 400: 요청이 아직 끝나지 않음(문서). 그 밖에 401/403/404/429/500.
                    log.warning("fal_delete_failed status=%s", r.status_code)
                else:
                    failed = 0
                    try:
                        res = r.json().get("cdn_delete_results") or []
                        failed = sum(1 for x in res if isinstance(x, dict) and x.get("exception"))
                    except Exception as e:
                        log.warning("fal_delete_unreadable error=%s", type(e).__name__)
                    if failed:
                        log.warning("fal_delete_partial failed_files=%d", failed)
            except Exception as e:
                log.warning("fal_delete_failed error=%s", type(e).__name__)
