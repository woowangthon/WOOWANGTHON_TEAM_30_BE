"""대화 답장에 붙일 그분 목소리 합성: synth_for_reply().

services/talk.py 의 generated_reply() 안에서 한 줄로 부르도록 만든 부품이다(연결은 이 파일이 하지 않는다).
인자는 generated_reply() 가 받는 것과 같다: (db, space, text, source_ids).

    audio = synth_for_reply(db, space, text, source_ids)   # "data:<mime>;base64,..." 또는 None

원칙
- 꺼져 있거나(YEOUN_VOICE_SYNTH != on) fal 키(YEOUN_FAL_API_KEY)가 없으면 None.
  config.py 를 고치지 않기 위해 두 값은 os.environ 에서 직접 읽는다.
- 어떤 경우에도 예외를 밖으로 던지지 않는다. 안 되면 None (답장 글자는 그대로 나간다).
- 정해진 목소리(NOVA 안내 목소리)로 대신 읽지 않는다. 그분 답장이 다른 목소리로 나오면 가족이 헷갈린다.
- 음성을 서버에 저장하지 않는다. 참조 음성도 합성 결과도 메모리에서만 다루고 임시 파일을 만들지 않는다.
- 로그에는 문장 내용·자막·파일명·키를 남기지 않는다(결과 코드, 클립 수, 길이, 걸린 시간만).

참조 음성
- 그분으로 확인된 클립(services/talk.py 의 person_clips(): included_expr() 기준, 그분을 부르며
  시작하는 말은 뺌) 중 재생 파일이 준비된 것에서 ref.py 기준으로 고른다. source_ids 는 우선 후보다.
- 클립 음성은 기존 경로(storage/blobstore.load: 복호화)로 읽는다. 클립 파일은 파이프라인이 이미
  구간대로 잘라 둔 mp3(pipeline/media.cut_clip: 24kHz mono 64kbps)라 다시 자르지 않는다.
- 여러 클립은 MP3 프레임을 이어 붙여 하나의 mp3 로 만든다(같은 인코더 설정이라 그대로 이어진다).
"""

from __future__ import annotations

import base64
import concurrent.futures
import importlib
import logging
import os
import time
from collections.abc import Callable, Iterable
from typing import Any

from app.voice.ref import RefCandidate, pick_reference

log = logging.getLogger("yeoun.voice")

# 합성 전체(참조 클립 읽기 + 합성 호출)의 시간 제한(초).
# 대화 답장이 이보다 오래 멈추지 않게 한다. 넘으면 합성을 버리고 None(답장 글자만 나간다).
# 넘긴 뒤에도 공급자 호출 스레드는 공급자 자체 시간 제한까지 뒤에서 끝나기를 기다리며, 결과는 버린다.
VOICE_REPLY_TIMEOUT_SEC = 15.0

ENV_SWITCH = "YEOUN_VOICE_SYNTH"  # "on" 일 때만 합성
ENV_FAL_KEY = "YEOUN_FAL_API_KEY"

# provider.synthesize 에 넘길 모델 이름(논리 이름). 실제 fal 모델 ID 로의 연결은 provider.py 가 맡는다.
DEFAULT_MODEL = "qwen3-tts"

MAX_TEXT_CHARS = 300  # talk.py 가 답장을 300자로 자르는 것과 맞춘다


def enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "").strip().lower() == "on"


def has_fal_key() -> bool:
    return bool(os.environ.get(ENV_FAL_KEY, "").strip())


# ---------------------------------------------------------------------------
# MP3 잇기 (순수 함수)


def _strip_id3v2(b: bytes) -> bytes:
    """앞쪽 ID3v2 태그를 뗀다 (헤더 10바이트 + syncsafe 크기, footer 플래그면 10바이트 더)."""
    if len(b) >= 10 and b[:3] == b"ID3":
        size = (b[6] & 0x7F) << 21 | (b[7] & 0x7F) << 14 | (b[8] & 0x7F) << 7 | (b[9] & 0x7F)
        end = 10 + size + (10 if b[5] & 0x10 else 0)
        return b[end:]
    return b


def _strip_id3v1(b: bytes) -> bytes:
    if len(b) >= 128 and b[-128:-125] == b"TAG":
        return b[:-128]
    return b


def join_mp3(parts: list[bytes]) -> bytes:
    """같은 설정으로 인코딩된 mp3 여러 개를 하나로 잇는다. 가운데 태그는 떼어 낸다."""
    out: list[bytes] = []
    n = len(parts)
    for i, p in enumerate(parts):
        if i > 0:
            p = _strip_id3v2(p)
        if i < n - 1:
            p = _strip_id3v1(p)
        out.append(p)
    return b"".join(out)


# ---------------------------------------------------------------------------
# 기본 의존성 (늦게 import: DB·설정 모듈을 이 파일 import 때 끌어오지 않는다)


def _default_clips_loader(db: Any, space_id: str) -> list[tuple[Any, Any]]:
    from app.services.talk import person_clips

    return person_clips(db, space_id)


def _default_load_audio(space: Any, key: str) -> bytes:
    from app.storage import blobstore

    return blobstore.load(space, key)


def _default_synthesize(text: str, ref_audio: bytes, ref_text: str, model: str) -> tuple[bytes, str, float]:
    provider = importlib.import_module("app.voice.provider")
    return provider.synthesize(text, ref_audio, ref_text, model)


# ---------------------------------------------------------------------------


class _Skip(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _ids(source_ids: Any) -> list[str]:
    if isinstance(source_ids, (str, bytes)) or source_ids is None:
        return []
    if not isinstance(source_ids, Iterable):
        return []
    try:
        return [str(i) for i in source_ids if isinstance(i, str) and i]
    except Exception:
        return []


def _duration(clip: Any) -> float:
    try:
        return float(clip.end_sec) - float(clip.start_sec)
    except Exception:
        return 0.0


def synth_for_reply(
    db: Any,
    space: Any,
    text: Any,
    source_ids: Any,
    *,
    clips_loader: Callable[[Any, str], list[tuple[Any, Any]]] | None = None,
    load_audio: Callable[[Any, str], bytes] | None = None,
    synthesize: Callable[[str, bytes, str, str], tuple[bytes, str, float]] | None = None,
    model: str = DEFAULT_MODEL,
    timeout_sec: float = VOICE_REPLY_TIMEOUT_SEC,
) -> str | None:
    """AI가 만든 답장 text 를 그분 목소리로 합성해 data 주소로 돌려준다. 안 되면 None.

    키워드 인자(clips_loader·load_audio·synthesize)는 테스트에서 바꿔 끼우는 자리다. 보통은 쓰지 않는다.
    """
    started = time.monotonic()
    try:
        url, n_clips, ref_sec = _run(
            db,
            space,
            text,
            source_ids,
            clips_loader=clips_loader or _default_clips_loader,
            load_audio=load_audio or _default_load_audio,
            synthesize=synthesize or _default_synthesize,
            model=model,
            timeout_sec=timeout_sec,
            started=started,
        )
    except _Skip as e:
        if e.code not in ("off", "no_key"):
            log.info("voice_reply skipped code=%s elapsed=%.2f", e.code, time.monotonic() - started)
        return None
    except Exception as e:  # 어떤 실패도 답장을 막지 않는다
        code = getattr(e, "code", None)
        code = code if isinstance(code, str) else type(e).__name__
        log.warning("voice_reply failed code=%s elapsed=%.2f", code, time.monotonic() - started)
        return None
    log.info(
        "voice_reply ok clips=%d ref_sec=%.1f elapsed=%.2f", n_clips, ref_sec, time.monotonic() - started
    )
    return url


def _run(
    db: Any,
    space: Any,
    text: Any,
    source_ids: Any,
    *,
    clips_loader: Callable[[Any, str], list[tuple[Any, Any]]],
    load_audio: Callable[[Any, str], bytes],
    synthesize: Callable[[str, bytes, str, str], tuple[bytes, str, float]],
    model: str,
    timeout_sec: float,
    started: float,
) -> tuple[str, int, float]:
    if not enabled():
        raise _Skip("off")
    if not has_fal_key():
        raise _Skip("no_key")
    if not isinstance(text, str) or not text.strip():
        raise _Skip("no_text")
    say = text.strip()[:MAX_TEXT_CHARS]
    space_id = getattr(space, "id", None)
    if db is None or not isinstance(space_id, str) or not space_id:
        raise _Skip("bad_args")

    def remaining() -> float:
        return timeout_sec - (time.monotonic() - started)

    # 그분으로 확인된 클립 중 재생 파일이 준비된 것
    rows = clips_loader(db, space_id) or []
    by_id: dict[str, Any] = {}
    cands: list[RefCandidate] = []
    for row in rows:
        clip = row[0] if isinstance(row, (tuple, list)) else row
        cid = getattr(clip, "id", None)
        if not isinstance(cid, str) or cid in by_id:
            continue
        if not getattr(clip, "audio_key", None) or getattr(clip, "audio_status", None) != "ready":
            continue
        by_id[cid] = clip
        cands.append(
            RefCandidate(id=cid, duration=_duration(clip), has_text=bool(str(getattr(clip, "text", "") or "").strip()))
        )
    pick = pick_reference(cands, _ids(source_ids))
    if not pick.usable:
        raise _Skip("ref_too_short")

    parts: list[bytes] = []
    texts: list[str] = []
    for cid in pick.ids:
        if remaining() <= 0:
            raise _Skip("timeout")
        clip = by_id[cid]
        data = load_audio(space, clip.audio_key)
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise _Skip("ref_unreadable")
        parts.append(bytes(data))
        t = str(getattr(clip, "text", "") or "").strip()
        if t:
            texts.append(t)
    ref_audio = join_mp3(parts)
    ref_text = " ".join(texts)

    left = remaining()
    if left <= 0:
        raise _Skip("timeout")
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="yeoun-voice")
    try:
        fut = ex.submit(synthesize, say, ref_audio, ref_text, model)
        try:
            result = fut.result(timeout=left)
        except concurrent.futures.TimeoutError as e:
            raise _Skip("timeout") from e
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    if not isinstance(result, (tuple, list)) or len(result) < 2:
        raise _Skip("bad_output")
    audio, mime = result[0], result[1]
    if not isinstance(audio, (bytes, bytearray)) or not audio:
        raise _Skip("bad_output")
    if not isinstance(mime, str) or not mime.startswith("audio/") or any(ch in mime for ch in ";, \r\n"):
        raise _Skip("bad_output")
    url = f"data:{mime};base64," + base64.b64encode(bytes(audio)).decode("ascii")
    return url, len(pick.ids), pick.total_sec
