"""여운 안내 목소리: 서비스 안내 문장을 정해진 목소리 하나로 읽어 준다(충북대 NOVA 게이트웨이 음성 합성).

guide_voice(text) -> "data:audio/wav;base64,..." | None

- 그분 목소리가 아니다. 그분 답장(app/voice/reply.py)에는 쓰지 않는다. 늘 같은 차분한 목소리 하나만 쓴다.
- 기본은 꺼 둔다: YEOUN_VOICE_GUIDE=on 일 때만 호출한다(os.environ 에서 직접 읽음).
- 키: 기존 api_key("nova") (환경변수 YEOUN_NOVA_API_KEY).
- 응답은 머리말 없는 원시 PCM(24000Hz, 모노, 16비트 LE) → 표준 wave 모듈로 WAV 로 감싼다(ffmpeg 불필요).
  응답 Content-Type 이 이미 wav/mpeg 이면 그대로 싣는다.
- 빈 문장, 4,000자 초과(자르지 않음), 403(모델 꺼짐), 429(한도), 503(점검), 시간 초과, 키 없음,
  이상한 응답: 모두 None. 어떤 입력에도 예외를 던지지 않는다.
- 로그에는 문장·키를 남기지 않는다(상태 코드·실패 코드만).

출처: https://docs.mindlogic.ai/docs/general/api-gateway/reference/audio-tts.md
"""

from __future__ import annotations

import base64
import io
import logging
import os
import wave

import httpx

log = logging.getLogger("yeoun.voice.guide")

ENV_SWITCH = "YEOUN_VOICE_GUIDE"  # "on" 일 때만 호출

# 주소. 출처: https://docs.mindlogic.ai/docs/general/api-gateway/reference/audio-tts.md
# (config.py 의 nova_base_url 기본값 + "/audio/speech/" 와 같은 주소다)
GUIDE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway/audio/speech/"
# 모델: 문서의 최신·권장 모델. 출처: 같은 문서
GUIDE_MODEL = "gemini-3.8-flash-tts"
# 목소리: 문서가 30종 중 "차분함"이라고 적은 것은 Schedar(남성) 하나. 출처: 같은 문서
GUIDE_VOICE = "Schedar"
# input 최대 4,000자. 출처: 같은 문서
MAX_INPUT_CHARS = 4000
# 응답 PCM 형식: 24,000Hz, 모노, 16비트 부호 있는 리틀 엔디안. 출처: 같은 문서
PCM_RATE = 24000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2

GUIDE_TIMEOUT_SEC = 20.0  # 안내 목소리 요청 하나의 시간 제한(초)


def enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "").strip().lower() == "on"


def pcm_to_wav(
    pcm: bytes, rate: int = PCM_RATE, channels: int = PCM_CHANNELS, width: int = PCM_SAMPLE_WIDTH
) -> bytes:
    frame = channels * width
    pcm = pcm[: len(pcm) - (len(pcm) % frame)]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


def _key() -> str | None:
    from app.ai.base import api_key

    return api_key("nova")


def guide_voice(text: object) -> str | None:
    try:
        return _guide_voice(text)
    except Exception as e:  # 어떤 경우에도 던지지 않는다
        log.warning("guide_voice failed code=%s", type(e).__name__)
        return None


def _guide_voice(text: object) -> str | None:
    if not enabled():
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    say = text.strip()
    if len(say) > MAX_INPUT_CHARS:
        log.info("guide_voice skipped code=too_long")
        return None
    key = _key()
    if not key:
        return None
    try:
        r = httpx.post(
            GUIDE_URL,
            headers={"Authorization": f"Bearer {key}"},
            # 필수 여부는 문서에 명시 없음(미확인) → model·input·voice 를 모두 보낸다.
            # speakers·instructions·response_format 은 보내지 않는다.
            json={"model": GUIDE_MODEL, "input": say, "voice": GUIDE_VOICE},
            timeout=GUIDE_TIMEOUT_SEC,
        )
    except httpx.TimeoutException:
        log.warning("guide_voice failed code=timeout")
        return None
    except httpx.HTTPError as e:
        log.warning("guide_voice failed code=%s", type(e).__name__)
        return None
    if r.status_code != 200:
        # 400(입력 초과 등), 403(조직에서 모델 비활성), 429(속도 제한), 503(점검)
        log.warning("guide_voice failed status=%s", r.status_code)
        return None
    data = r.content
    if not data:
        log.warning("guide_voice failed code=empty")
        return None
    ctype = (r.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if ctype in ("audio/wav", "audio/x-wav", "audio/wave"):
        mime, body = "audio/wav", data
    elif ctype in ("audio/mpeg", "audio/mp3"):
        mime, body = "audio/mpeg", data
    elif ctype in ("audio/pcm", "audio/l16"):
        body = pcm_to_wav(data)
        if len(body) <= 44:  # 표본이 하나도 없음
            log.warning("guide_voice failed code=empty")
            return None
        mime = "audio/wav"
    else:
        log.warning("guide_voice failed code=bad_content_type")
        return None
    return f"data:{mime};base64," + base64.b64encode(body).decode("ascii")
