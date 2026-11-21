"""그분 목소리 합성 공급자: fal(실제) / mock(명시적으로 고를 때만, 테스트·개발용).

synthesize(text, ref_audio, ref_text, model, *, ref_seconds, ref_mime, timeout, provider="fal",
           wait_cleanup=False) -> (audio, mime, 걸린 초)
wait_for_cleanups(timeout=None) -> bool   # 뒤에서 도는 정리(취소·삭제)가 모두 끝날 때까지 기다린다

- provider="fal"(기본): 키(YEOUN_FAL_API_KEY)가 없으면 ProviderError("not_configured"). 무음으로 대신하지 않는다.
- provider="mock": 네트워크 없이 짧은 무음 WAV. 명시적으로 고른 경우에만 쓴다.
  app/voice/reply.py(그분 답장)는 언제나 provider="fal" 로 부르므로 mock 을 쓰지 않는다.

- 모델(논리 이름 → fal endpoint_id)
    "qwen3-tts"  : Qwen3-TTS 1.7B. 복제(clone-voice) → 합성(text-to-speech) 2단계
    "chatterbox" : Chatterbox Multilingual. 참조 음성 주소를 voice 로 넣는 1단계
- 참조 음성이 3초 미만이거나 길이를 알 수 없으면 호출하지 않고 ProviderError("ref_too_short") 로 거절한다.
  300초를 넘으면 호출하지 않고 ProviderError("bad_input") (MAX_REF_SEC).
- 긴 문장은 문장 단위로 묶어 조각(Chatterbox 300자, Qwen 100자 이하)으로 나눠 요청하고, 결과를 이어 붙인다.
- 호출은 큐 방식이다: 제출 → 응답의 status_url 폴링 → response_url 결과 → audio.url 내려받기 → 삭제 API.
  (삭제 API 에 필요한 request_id 는 큐 제출 응답에서 얻는다.)
- 개인정보 헤더:
    · 제출, 합성 중 상태 폴링, 결과 요청: Authorization, X-Fal-Store-IO: 0, X-Fal-Object-Lifecycle-Preference,
      X-Fal-Request-Start-Timeout (4개)
    · 정리 단계의 취소·상태 확인·삭제 요청: Authorization, X-Fal-Store-IO: 0 (2개. 보관 기간·시작 대기 헤더 없음)
    · 결과 파일(CDN) 내려받기: 헤더 없음(키를 보내지 않는다)
  참조 음성은 fal CDN 에 올리지 않고 data 주소로 요청 본문에 직접 싣는다.
- 키를 붙이는 주소: 제출 주소(FAL_QUEUE_BASE), 삭제 주소(FAL_DELETE_URL)는 상수다. fal 응답이 준
  status_url·response_url·cancel_url 은 https://queue.fal.run 주소일 때만 쓰고, 아니면 bad_output 으로 끝낸다
  (키가 다른 호스트로 나가지 않게).
- 정리: 결과(또는 오류)를 먼저 호출자에게 돌려주고, 정리는 그 뒤 별도 데몬 스레드에서 돈다
  (wait_cleanup=True 면 돌려주기 전에 같은 스레드에서 끝까지 정리한다. 평가·미리 듣기용).
  정리 스레드 안의 모든 예외(BaseException 포함)는 삼키고 코드만 로그에 남긴다. 데몬 스레드라 서버 프로세스가
  끝나면 정리가 끊길 수 있다 → 그 경우도 보관 기간 헤더에만 의존한다.
  생긴 request_id 마다 결과 파일 삭제 API 를 부른다.
  끝나지 않은 요청은 먼저 취소(cancel_url)하고, 정리 한도(CLEANUP_TIMEOUT_SEC) 안에서 status_url 을 짧게
  확인해 끝난 것으로 보이면 삭제한다(문서: 끝나지 않은 요청의 삭제는 400). 그래도 지우지 못하면 예외 없이
  코드만 로그에 남긴다("fal_payload_not_deleted").
  한계: 그 경우 fal 쪽 결과 파일은 보관 기간 헤더(OBJECT_LIFECYCLE_SEC=3600초)에만 의존해 사라진다.
  취소된 요청이 상태 확인에서 어떻게 보이는지(COMPLETED 로 바뀌는지)와 그 뒤 삭제가 되는지는 실제 fal 동작으로
  미확인이다.
- 로그·오류 detail 에 문장·자막·파일명·키·주소(서명이 붙을 수 있음)를 남기지 않는다.

미확인(실제 호출로 확인 필요):
- Qwen text-to-speech 의 max_new_tokens 기본값이 200(문서)인데 이 값은 보내지 않는다. 음성 토큰과 글자 수의
  비율이 미확인이라 긴 조각이 잘린 채 나올 수 있다 → Qwen 조각 상한을 보수적으로 100자로 잡았다.
- 그 밖의 미확인 항목은 각 상수 주석에 있다.

ProviderError 코드(app/ai/base.py 의 목록에 더해 이 모듈이 쓰는 것):
    not_configured : fal 키 없음 (provider="fal")
    bad_input      : 빈 문장·빈 참조·참조 300초 초과·모르는 모델·모르는 참조 형식·모르는 provider
    ref_too_short  : 참조 음성 3초 미만이거나 길이를 알 수 없음
    timeout        : 전체 상한 초과 또는 HTTP 시간 초과
    http_error     : HTTP 오류·fal 이 알린 오류(error/error_type)
    bad_output     : 응답 모양이 이상함, 음성 서명이 아님, 형식이 섞임, 응답 주소가 큐 호스트가 아님

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
import threading
import time
import wave
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.ai.base import ProviderError

log = logging.getLogger("yeoun.voice.provider")

ENV_FAL_KEY = "YEOUN_FAL_API_KEY"

# --- fal 주소 ------------------------------------------------------------------
# 큐 제출: POST https://queue.fal.run/<endpoint_id>. 상태·결과·취소 주소는 제출 응답이 준 것을 그대로 쓴다.
# 출처: https://fal.ai/docs/model-apis/model-endpoints/queue
# 하위 경로가 있는 endpoint_id 를 제출 주소에 그대로 쓰는 것은 문서 예시 기준이며 실제 호출로는 미확인.
FAL_QUEUE_BASE = "https://queue.fal.run/"
FAL_QUEUE_HOST = (
    "queue.fal.run"  # 응답이 준 status_url·response_url·cancel_url 이 이 호스트일 때만 키를 붙인다
)
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
# 참조 음성 최대 길이(초). Qwen 복제 audio_url 최대 300초
# (출처: https://fal.ai/models/fal-ai/qwen-3-tts/clone-voice/1.7b/api).
# Chatterbox 의 참조 길이 상한은 미확인 → 같은 값을 보수적으로 적용한다.
MAX_REF_SEC = 300.0
# Chatterbox text 최대 300자 (출처: https://fal.ai/models/fal-ai/chatterbox/text-to-speech/multilingual/api).
MAX_CHUNK_CHARS = 300
# Qwen 조각 상한(글자). Qwen 의 text 글자 수 제한은 미확인이고, max_new_tokens 기본 200(문서)을 보내지 않으므로
# 긴 조각이 잘릴 수 있다. 미확인이라 보수적으로 잡은 값이며 실제 호출로 확인 필요.
QWEN_MAX_CHUNK_CHARS = 100

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
# 정리 한도(초): 끝나지 않은 요청 하나의 '취소 + 상태 확인' 전체 상한, 그리고 삭제 요청 하나의 상한.
# 전체 상한(timeout)이 지난 뒤에도 정리는 이 한도 안에서 시도한다.
CLEANUP_TIMEOUT_SEC = 5.0
POLL_INTERVAL_SEC = 0.5  # 상태 폴링 간격

_sleep = time.sleep  # 테스트에서 바꿔 끼운다


# =============================================================================
# 공통 도우미


def fal_key() -> str | None:
    v = os.environ.get(ENV_FAL_KEY, "").strip()
    return v or None


def _is_queue_url(url: str) -> bool:
    """키를 붙여도 되는 주소인지: research.md 의 큐 호스트(queue.fal.run)의 https 주소만."""
    try:
        u = urlsplit(url)
        return (
            u.scheme == "https" and u.hostname == FAL_QUEUE_HOST and u.port in (None, 443) and not u.username
        )
    except ValueError:
        return False


def sniff_mime(data: bytes) -> str | None:
    """파일 앞부분 서명으로 형식을 판별한다(WAV/MPEG 만).

    WAV: RIFF....WAVE. MPEG: ID3 태그 또는 프레임 동기(11비트) + 버전·레이어가 예약값이 아님
    (레이어 00 인 AAC ADTS 는 MPEG 오디오로 보지 않는다).
    """
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:3] == b"ID3":
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        if ((data[1] >> 3) & 3) != 1 and ((data[1] >> 1) & 3) != 0:
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


_WORD = re.compile(r"\w")
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
        if not _WORD.search(p):  # 문장부호만 남은 조각은 소리가 없으므로 따로 보내지 않는다
            if chunks and len(chunks[-1]) + len(p) <= limit:
                chunks[-1] = chunks[-1] + p
            continue
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
    provider: str = "fal",
    wait_cleanup: bool = False,
) -> tuple[bytes, str, float]:
    """그분 목소리로 text 를 합성한다. 실패는 ProviderError(code) 로 올린다.

    provider="fal"(기본)은 키가 없으면 not_configured. provider="mock" 은 명시적으로 고를 때만 무음 WAV.
    wait_cleanup=False(기본)면 fal 정리(취소·삭제)를 뒤의 데몬 스레드로 넘기고 바로 돌려준다.
    True 면 돌려주기 전에 정리까지 끝낸다(평가·미리 듣기처럼 정리 완료를 기다려야 할 때).
    """
    started = time.monotonic()
    if provider not in ("fal", "mock"):
        raise ProviderError("bad_input", "unknown provider")
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
    if secs_f > MAX_REF_SEC:
        raise ProviderError("bad_input", f"reference over {MAX_REF_SEC:.0f}s")
    limit = QWEN_MAX_CHUNK_CHARS if model == MODEL_QWEN else MAX_CHUNK_CHARS
    chunks = split_text(text.strip(), limit)
    if not chunks:
        raise ProviderError("bad_input", "empty text")
    if provider == "mock":
        audio, out_mime = silent_wav(), "audio/wav"
    else:
        key = fal_key()
        if key is None:
            raise ProviderError("not_configured", "fal key missing")
        try:
            budget = max(0.0, float(timeout))
        except (TypeError, ValueError):
            budget = DEFAULT_TIMEOUT_SEC
        job = _FalJob(key, started + budget)
        try:
            audio, out_mime = job.run(
                model, chunks, ref_audio, mime, ref_text if isinstance(ref_text, str) else ""
            )
        finally:
            # 결과(또는 오류)를 먼저 돌려주고 정리는 뒤에서 한다. wait_cleanup=True 면 여기서 끝까지 정리.
            if wait_cleanup:
                _run_cleanup(job)
            elif job.requests:
                _start_cleanup(job)
    return audio, out_mime, time.monotonic() - started


# =============================================================================
# 뒤에서 도는 정리

_cleanups: set[threading.Thread] = set()
_cleanups_lock = threading.Lock()


def _run_cleanup(job: _FalJob) -> None:
    try:
        job.cleanup()
    except BaseException as e:  # noqa: BLE001 - 정리는 어떤 경우에도 밖으로 새지 않는다
        log.warning("fal_cleanup_crashed error=%s", type(e).__name__)


def _start_cleanup(job: _FalJob) -> threading.Thread:
    def body() -> None:
        try:
            _run_cleanup(job)
        finally:
            with _cleanups_lock:
                _cleanups.discard(t)

    t = threading.Thread(target=body, name="yeoun-voice-cleanup", daemon=True)
    with _cleanups_lock:
        _cleanups.add(t)
    t.start()
    return t


def wait_for_cleanups(timeout: float | None = None) -> bool:
    """뒤에서 도는 정리 스레드가 모두 끝날 때까지 기다린다. 다 끝났으면 True."""
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        with _cleanups_lock:
            pending = list(_cleanups)
        if not pending:
            return True
        for t in pending:
            left = None if deadline is None else max(0.0, deadline - time.monotonic())
            t.join(left)
        if deadline is not None and time.monotonic() >= deadline:
            with _cleanups_lock:
                return not any(t.is_alive() for t in _cleanups)


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
        # 응답이 준 주소에는 키를 붙여 요청하므로 큐 호스트의 https 주소만 쓴다. 아니면 그 주소는 버리고
        # (정리 단계에서도 쓰지 않는다) bad_output. request_id 는 삭제 API(상수 호스트)로 정리한다.
        bad = False
        for k in ("status_url", "response_url", "cancel_url"):
            if req[k] and not _is_queue_url(req[k]):
                req[k] = ""
                bad = True
        if not req["status_url"] or not req["response_url"]:
            bad = True
        self.requests.append(req)
        if bad:
            raise ProviderError("bad_output", "unexpected queue url")
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
        # 형식: File 의 content_type → HTTP 응답 헤더 → 파일 앞부분 서명 순으로 정하고,
        # 언제나 서명으로 교차 확인한다(200 에 HTML 등이 와도 음성으로 통과시키지 않는다).
        signed = sniff_mime(data)
        if signed is None:
            raise ProviderError("bad_output", "not audio")
        mime = _norm_mime(file.get("content_type")) or _norm_mime(r.headers.get("content-type")) or signed
        if mime != signed:
            raise ProviderError("bad_output", "content type mismatch")
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

    def _settle(self, req: dict[str, Any]) -> bool:
        """끝나지 않은 요청을 취소하고, 정리 한도 안에서 status_url 을 짧게 확인해 끝났는지 본다.

        취소된 요청이 상태 확인에서 COMPLETED 로 보이는지는 실제 fal 동작으로 미확인이다.
        """
        until = time.monotonic() + CLEANUP_TIMEOUT_SEC
        if req.get("cancel_url"):
            try:
                r = httpx.request(
                    "PUT", req["cancel_url"], headers=self._cleanup_headers(), timeout=CLEANUP_TIMEOUT_SEC
                )
                if r.status_code >= 300:
                    log.warning("fal_cancel_failed status=%s", r.status_code)
            except Exception as e:
                log.warning("fal_cancel_failed error=%s", type(e).__name__)
        if not req.get("status_url"):  # 큐 호스트가 아닌 주소였으면 확인하지 않는다
            return False
        while True:
            left = until - time.monotonic()
            if left <= 0:
                return False
            try:
                r = httpx.request("GET", req["status_url"], headers=self._cleanup_headers(), timeout=left)
                st = r.json() if r.status_code in (200, 202) else None
                if isinstance(st, dict) and st.get("status") == "COMPLETED":
                    return True
            except Exception as e:
                log.warning("fal_cleanup_status_failed error=%s", type(e).__name__)
            left = until - time.monotonic()
            if left <= 0:
                return False
            _sleep(min(POLL_INTERVAL_SEC, left))

    def cleanup(self) -> None:
        """끝나지 않은 요청은 취소·확인하고, 모든 request_id 의 결과 파일을 삭제한다. 예외를 올리지 않는다."""
        for req in self.requests:
            finished = True
            if not req.get("done"):
                try:
                    finished = self._settle(req)
                except Exception as e:
                    finished = False
                    log.warning("fal_cleanup_status_failed error=%s", type(e).__name__)
            try:
                # 끝났는지 확인하지 못했어도 한 번은 시도한다(실패하면 아래에서 '지우지 못함' 로그).
                r = httpx.request(
                    "DELETE",
                    FAL_DELETE_URL.format(request_id=quote(req["id"], safe="")),
                    headers=self._cleanup_headers(),
                    timeout=CLEANUP_TIMEOUT_SEC,
                )
                if r.status_code != 200:
                    # 400: 요청이 아직 끝나지 않음(문서). 그 밖에 401/403/404/429/500.
                    # 이 경우 결과 파일은 보관 기간 헤더(OBJECT_LIFECYCLE_SEC)에만 의존한다.
                    log.warning(
                        "fal_payload_not_deleted status=%s finished=%s",
                        r.status_code,
                        "yes" if finished else "no",
                    )
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
                log.warning("fal_payload_not_deleted error=%s", type(e).__name__)
