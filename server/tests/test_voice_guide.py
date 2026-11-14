"""여운 안내 목소리(app/voice/guide.py) 테스트. 실제 네트워크 없이 guide 모듈의 httpx.post 를 가짜로 바꾼다."""

from __future__ import annotations

import base64
import io
import logging
import wave

import httpx
import pytest

from app.voice import guide as G

FAKE_KEY = "nova-test-not-a-real-key"  # 테스트 전용 가짜 값
PCM = b"\x01\x00\xff\x7f" * 2400  # 16비트 표본 4800개 = 0.2초


@pytest.fixture
def nova(monkeypatch):
    monkeypatch.setenv(G.ENV_SWITCH, "on")
    monkeypatch.setattr(G, "_key", lambda: FAKE_KEY)
    calls: list[dict] = []

    def install(response=None, exc: Exception | None = None):
        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            if exc:
                raise exc
            return response or httpx.Response(200, content=PCM, headers={"content-type": "audio/pcm"})

        monkeypatch.setattr(G.httpx, "post", fake_post)
        return calls

    return install


def decode(url: str) -> tuple[str, bytes]:
    head, b64 = url.split(",", 1)
    return head, base64.b64decode(b64)


def test_pcm_is_wrapped_as_wav(nova):
    calls = nova()
    url = G.guide_voice("녹음을 올려 주세요.")
    head, data = decode(url)
    assert head == "data:audio/wav;base64"
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.readframes(w.getnframes()) == PCM
    c = calls[0]
    assert c["url"] == "https://factchat-cloud.mindlogic.ai/v1/gateway/audio/speech/"
    assert c["headers"] == {"Authorization": f"Bearer {FAKE_KEY}"}
    assert c["json"] == {"model": "gemini-3.8-flash-tts", "input": "녹음을 올려 주세요.", "voice": "Schedar"}
    assert c["timeout"] == G.GUIDE_TIMEOUT_SEC


def test_riff_body_without_pcm_content_type_returns_none(nova):
    """문서에 없는 분기는 두지 않는다: RIFF WAV 본문이어도 Content-Type 이 audio/pcm 이 아니면 None."""
    body = G.pcm_to_wav(PCM)
    for ctype in ("audio/wav", "text/html", None):
        nova(httpx.Response(200, content=body, headers={"content-type": ctype} if ctype else {}))
        assert G.guide_voice("안내") is None, ctype


def test_content_types_not_in_docs_return_none(nova):
    for ctype in ("audio/mpeg", "audio/l16", "audio/wav", "application/octet-stream"):
        nova(httpx.Response(200, content=b"\xff\xfb\x90\x00" * 10, headers={"content-type": ctype}))
        assert G.guide_voice("안내") is None, ctype


def test_pcm_to_wav_drops_partial_frame():
    data = G.pcm_to_wav(b"\x01\x00\x02")
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getnframes() == 1


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_error_status_returns_none(nova, status):
    nova(httpx.Response(status, json={"detail": "x"}))
    assert G.guide_voice("안내") is None


def test_timeout_and_network_error_return_none(nova):
    nova(exc=httpx.ReadTimeout("slow"))
    assert G.guide_voice("안내") is None
    nova(exc=httpx.ConnectError("down"))
    assert G.guide_voice("안내") is None
    nova(exc=RuntimeError("anything"))
    assert G.guide_voice("안내") is None


def test_weird_responses_return_none(nova):
    for resp in [
        httpx.Response(200, content=b""),
        httpx.Response(200, content=b"\x00", headers={"content-type": "audio/pcm"}),
        httpx.Response(200, json={"error": "x"}),
        httpx.Response(200, content=PCM),  # Content-Type 없음
    ]:
        nova(resp)
        assert G.guide_voice("안내") is None


def test_off_by_default(nova, monkeypatch):
    calls = nova()
    monkeypatch.delenv(G.ENV_SWITCH)
    assert G.guide_voice("안내") is None
    monkeypatch.setenv(G.ENV_SWITCH, "off")
    assert G.guide_voice("안내") is None
    assert calls == []


def test_no_key_returns_none(nova, monkeypatch):
    calls = nova()
    monkeypatch.setattr(G, "_key", lambda: None)
    assert G.guide_voice("안내") is None

    def broken():
        raise RuntimeError("settings")

    monkeypatch.setattr(G, "_key", broken)
    assert G.guide_voice("안내") is None
    assert calls == []


def test_real_key_lookup_uses_nova_setting(monkeypatch):
    """_key() 는 기존 api_key("nova") (YEOUN_NOVA_API_KEY) 를 쓴다."""
    from app.config import reset_settings_cache

    monkeypatch.setenv("YEOUN_NOVA_API_KEY", FAKE_KEY)
    reset_settings_cache()
    try:
        assert G._key() == FAKE_KEY
        monkeypatch.delenv("YEOUN_NOVA_API_KEY")
        reset_settings_cache()
        assert G._key() is None
    finally:
        reset_settings_cache()


def test_empty_too_long_and_weird_inputs(nova):
    calls = nova()
    for bad in [None, "", "   ", 123, b"bytes", ["a"], "가" * 4001]:
        assert G.guide_voice(bad) is None
    assert calls == []
    assert G.guide_voice("가" * 4000) is not None  # 4,000자까지는 자르지 않고 그대로 보낸다
    assert len(calls[0]["json"]["input"]) == 4000


def test_logs_have_no_text_or_key(nova, caplog):
    nova(httpx.Response(429))
    with caplog.at_level(logging.DEBUG, logger="yeoun.voice.guide"):
        assert G.guide_voice("비밀안내문장") is None
    assert "status=429" in caplog.text
    assert "비밀안내문장" not in caplog.text and FAKE_KEY not in caplog.text
