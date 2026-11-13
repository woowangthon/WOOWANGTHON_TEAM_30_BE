"""충북대 NOVA API Gateway 어댑터: 실제 네트워크 없이 요청 형식과 응답 해석만 확인한다."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
from pydantic import SecretStr

from app.config import get_settings
from app.schemas import TranscriptSegment


def _use_nova(monkeypatch, *, auto: bool = True):
    s = get_settings()
    monkeypatch.setattr(s, "nova_api_key", SecretStr("nova-test-key"))
    if auto:
        for fn in ("stt", "diarization", "llm", "embedding"):
            monkeypatch.setattr(s, f"{fn}_provider", "auto")
    return s


def test_nova_is_preferred_when_key_set(monkeypatch):
    from app.ai import registry

    s = _use_nova(monkeypatch)
    monkeypatch.setattr(s, "anthropic_api_key", SecretStr("anthropic-key"))
    monkeypatch.setattr(s, "openai_api_key", SecretStr("openai-key"))
    for fn in ("stt", "diarization", "llm", "embedding"):
        res = registry.resolve(fn)
        assert res.name == "nova", fn
        assert res.meta.is_external and not res.meta.trains_on_input
        assert "NOVA" in res.meta.display_name
    assert registry.live_stt_available()


def test_nova_stt_start_then_poll(monkeypatch, tmp_path):
    from app.ai import stt as stt_mod

    _use_nova(monkeypatch)
    monkeypatch.setattr(stt_mod.time, "sleep", lambda _s: None)

    def fake_encode(src, dst, start=None, duration=None):
        Path(dst).write_bytes(b"ID3fake")

    monkeypatch.setattr(stt_mod.media, "encode_for_upload", fake_encode)
    calls: list[tuple[str, str, dict]] = []

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        calls.append(("POST", url, dict(data or {})))
        assert headers["Authorization"] == "Bearer nova-test-key"
        assert "file" in files
        return httpx.Response(200, json={"operation_id": "op/1+x", "duration_seconds": 12.0, "credits_charged": 1.2})

    polls = iter(
        [
            {"status": "processing"},
            {
                "status": "completed",
                "text": "밥은 먹었니? 응 먹었어요.",
                "segments": [
                    {"speaker": "Speaker 1", "text": "밥은 먹었니?", "start_ms": 0, "end_ms": 1800},
                    {"speaker": "Speaker 2", "text": "응 먹었어요.", "start_ms": 2000, "end_ms": 3500},
                    {"speaker": "Speaker 1", "text": "  ", "start_ms": 3600, "end_ms": 3700},
                ],
            },
        ]
    )

    def fake_get(url, headers=None, timeout=None):
        calls.append(("GET", url, {}))
        return httpx.Response(200, json=next(polls))

    monkeypatch.setattr(stt_mod.httpx, "post", fake_post)
    monkeypatch.setattr(stt_mod.httpx, "get", fake_get)

    stt = stt_mod.build("nova")
    segs = stt.transcribe(tmp_path / "a.wav", sha256=None, duration=12.0)

    assert [c[0] for c in calls] == ["POST", "GET", "GET"]
    assert calls[0][1].endswith("/v1/gateway/audio/transcriptions/")
    assert calls[0][2]["model"] == "stt-async-v5"
    assert calls[0][2]["enable_speaker_diarization"] == "true"
    assert calls[1][1].endswith("/audio/transcriptions/op%2F1%2Bx/")  # operation_id는 그대로 인코딩
    assert [(s.start, s.end, s.text, s.speaker) for s in segs] == [
        (0.0, 1.8, "밥은 먹었니?", "S1"),
        (2.0, 3.5, "응 먹었어요.", "S2"),
    ]


def test_nova_stt_failed_job_raises(monkeypatch, tmp_path):
    import pytest

    from app.ai import stt as stt_mod
    from app.ai.base import ProviderError

    _use_nova(monkeypatch)
    monkeypatch.setattr(stt_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(stt_mod.media, "encode_for_upload", lambda src, dst, **k: Path(dst).write_bytes(b"x"))
    monkeypatch.setattr(stt_mod.httpx, "post", lambda *a, **k: httpx.Response(200, json={"operation_id": "op"}))
    monkeypatch.setattr(
        stt_mod.httpx, "get", lambda *a, **k: httpx.Response(200, json={"status": "failed", "error": "boom"})
    )
    with pytest.raises(ProviderError):
        stt_mod.build("nova").transcribe(tmp_path / "a.wav", sha256=None, duration=5.0)

    monkeypatch.setattr(stt_mod.httpx, "post", lambda *a, **k: httpx.Response(402, json={"error": "credits"}))
    with pytest.raises(ProviderError):  # 크레딧 부족 → 파이프라인이 stt_failed로 처리
        stt_mod.build("nova").transcribe(tmp_path / "a.wav", sha256=None, duration=5.0)


def test_nova_diarizer_keeps_stt_speakers(monkeypatch, tmp_path):
    from app.ai import diarization

    _use_nova(monkeypatch)
    d = diarization.build("nova")
    segs = [
        TranscriptSegment(start=0, end=1, text="가", speaker="S1"),
        TranscriptSegment(start=1, end=2, text="나", speaker="S2"),
    ]
    out, ok = d.diarize(tmp_path / "a.wav", segs, 2.0)
    assert ok and [s.speaker for s in out] == ["S1", "S2"]
    out, ok = d.diarize(tmp_path / "a.wav", [s.model_copy(update={"speaker": None}) for s in segs], 2.0)
    assert not ok and all(s.speaker is None for s in out)


def test_nova_llm_uses_claude_gateway_and_falls_back_to_prompt_schema(monkeypatch):
    import anthropic

    from app.ai import llm as llm_mod

    _use_nova(monkeypatch)
    model = llm_mod.build("nova")
    assert model.name == "nova" and model.model == "claude-haiku-5-5"
    assert str(model.client.base_url).rstrip("/").endswith("/v1/gateway/claude")

    seen: list[dict] = []

    def fake_create(**kwargs):
        seen.append(kwargs)
        if "output_config" in kwargs:
            req = httpx.Request("POST", "https://example.invalid/v1/messages")
            raise anthropic.BadRequestError(
                "output_config not supported", response=httpx.Response(400, request=req), body=None
            )
        block = SimpleNamespace(type="text", text='```json\n{"intent": "food", "keywords": ["김치찌개"], "tags": [], "risk": "none"}\n```')
        return SimpleNamespace(stop_reason="end_turn", content=[block])

    monkeypatch.setattr(model.client.messages, "create", fake_create)
    out = model.parse_intent("김치찌개 어떻게 끓였어?")
    assert out["intent"] == "food"
    assert "output_config" in seen[0] and "output_config" not in seen[1]
    assert "JSON 스키마" in seen[1]["system"]
    model.parse_intent("또 물어볼게")  # 한 번 거절된 뒤에는 바로 프롬프트 방식
    assert "output_config" not in seen[2]


def test_nova_embedding_url(monkeypatch):
    from app.ai import embedding

    _use_nova(monkeypatch)
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"], seen["model"] = url, json["model"]
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    monkeypatch.setattr(embedding.httpx, "post", fake_post)
    vecs = embedding.build("nova").embed(["안녕"])
    assert vecs == [[0.1, 0.2]]
    assert seen["url"].endswith("/v1/gateway/embeddings/") and seen["model"] == "text-embedding-3-small"
