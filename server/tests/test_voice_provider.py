"""그분 목소리 합성 공급자(app/voice/provider.py) 테스트.

실제 네트워크 없이 provider 모듈이 쓰는 httpx.request 를 가짜로 바꿔 끼운다(test_nova.py 와 같은 방식).
요청 본문 필드 이름·개인정보 헤더는 문서-조사 결과(fal 공식 문서)와 같아야 한다.
"""

from __future__ import annotations

import io
import json
import logging
import threading
import time
import wave

import httpx
import pytest

from app.ai.base import ProviderError
from app.voice import provider as P

FAKE_KEY = "fal-test-not-a-real-key"  # 테스트 전용 가짜 값
EMB_URL = "https://v3.fal.media/files/emb/secret_embedding.safetensors"


def wav(seconds: float = 0.2, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return out.getvalue()


MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 100
REF = b"ID3\x04\x00\x00\x00\x00\x00\x00" + MP3  # mp3 참조(길이는 ref_seconds 로 받음)


class FakeFal:
    """fal 큐·CDN·삭제 API 를 흉내 낸다."""

    def __init__(
        self,
        *,
        audio=None,
        audio_ct="audio/wav",
        status_seq=None,
        status_error=None,
        delete_status=200,
        fail_on=None,
        raise_timeout_on=None,
        cancel_completes=True,
    ):
        self.calls: list[dict] = []
        self.n = 0
        self.endpoint_of: dict[str, str] = {}
        self.audio = audio if audio is not None else [wav()]
        self.audio_ct = audio_ct
        self.status_seq = list(status_seq or [])
        self.status_error = status_error
        self.delete_status = delete_status
        self.fail_on = fail_on
        self.raise_timeout_on = raise_timeout_on
        self.tts_count = 0
        self.cancel_completes = cancel_completes
        self.cancelled: set[str] = set()
        self.finished: set[str] = set()

    def __call__(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers or {}), "json": json, "timeout": timeout}
        )
        if self.raise_timeout_on and self.raise_timeout_on in url:
            raise httpx.ReadTimeout("slow")
        if method == "POST" and url.startswith("https://queue.fal.run/"):
            self.n += 1
            rid = f"req-{self.n}"
            ep = url[len("https://queue.fal.run/") :]
            self.endpoint_of[rid] = ep
            base = f"https://queue.fal.run/fal-ai/x/requests/{rid}"
            return httpx.Response(
                200,
                json={
                    "request_id": rid,
                    "status_url": base + "/status",
                    "response_url": base,
                    "cancel_url": base + "/cancel",
                    "queue_position": 0,
                },
            )
        if method == "GET" and url.endswith("/status"):
            rid = url.split("/requests/")[1].split("/")[0]
            if rid in self.cancelled:
                st = "COMPLETED" if self.cancel_completes else "IN_PROGRESS"
                return httpx.Response(200, json={"status": st})
            if self.status_error:
                return httpx.Response(
                    200, json={"status": "COMPLETED", "error": "boom", "error_type": self.status_error}
                )
            st = self.status_seq.pop(0) if self.status_seq else "COMPLETED"
            return httpx.Response(202 if st != "COMPLETED" else 200, json={"status": st})
        if method == "GET" and url.startswith("https://queue.fal.run/"):
            rid = url.rsplit("/", 1)[-1]
            ep = self.endpoint_of[rid]
            self.finished.add(rid)
            if self.fail_on and self.fail_on in ep:
                return httpx.Response(500, json={"detail": "server error"})
            if ep == P.QWEN_CLONE_ENDPOINT:
                return httpx.Response(
                    200,
                    json={
                        "speaker_embedding": {
                            "url": EMB_URL,
                            "content_type": "application/octet-stream",
                            "file_name": "x.safetensors",
                            "file_size": 10,
                        }
                    },
                )
            i = self.tts_count
            self.tts_count += 1
            ct = self.audio_ct[i] if isinstance(self.audio_ct, list) else self.audio_ct
            return httpx.Response(
                200, json={"audio": {"url": f"https://v3.fal.media/files/out/{rid}.bin", "content_type": ct}}
            )
        if method == "GET" and "fal.media" in url:
            return httpx.Response(200, content=self.audio[0])
        if method == "PUT":
            rid = url.split("/requests/")[1].split("/")[0]
            self.cancelled.add(rid)
            if self.cancel_completes:
                self.finished.add(rid)
            return httpx.Response(200, json={})
        if method == "DELETE":
            rid = url.split("/requests/")[1].split("/")[0]
            if rid not in self.finished:  # 문서: 끝나지 않은 요청은 400
                return httpx.Response(400, json={"detail": "not finished"})
            return httpx.Response(self.delete_status, json={"cdn_delete_results": []})
        raise AssertionError(f"unexpected {method} {url}")

    def of(self, method, contains=""):
        return [c for c in self.calls if c["method"] == method and contains in c["url"]]


@pytest.fixture
def fal(monkeypatch):
    monkeypatch.setenv(P.ENV_FAL_KEY, FAKE_KEY)
    monkeypatch.setattr(P, "_sleep", lambda s: time.sleep(0.005))
    monkeypatch.setattr(P, "CLEANUP_TIMEOUT_SEC", 0.3)  # 정리 한도를 줄여 테스트를 빠르게

    def install(**kw):
        f = FakeFal(**kw)
        monkeypatch.setattr(P.httpx, "request", f)
        return f

    yield install
    # 뒤에서 도는 정리가 가짜 HTTP 를 되돌리기 전에 끝나야 한다(실제 네트워크로 새지 않게)
    assert P.wait_for_cleanups(5)


def deleted_ids(f: FakeFal) -> list[str]:
    assert P.wait_for_cleanups(5)  # 정리는 뒤의 스레드에서 돈다
    return [c["url"].split("/requests/")[1].split("/")[0] for c in f.of("DELETE", "api.fal.ai")]


# --- 3초 미만 거절 -------------------------------------------------------------


def test_reference_under_3s_is_rejected_without_calling(fal):
    f = fal()
    with pytest.raises(ProviderError) as e:
        P.synthesize("안녕", REF, "자막", "qwen3-tts", ref_seconds=2.9, ref_mime="audio/mpeg")
    assert e.value.code == "ref_too_short"
    assert f.calls == []


def test_unknown_reference_length_is_rejected(fal):
    f = fal()
    with pytest.raises(ProviderError) as e:
        P.synthesize("안녕", REF, "자막", "qwen3-tts")  # mp3, 길이 모름
    assert e.value.code == "ref_too_short"
    for bad in ("x", float("nan")):
        with pytest.raises(ProviderError):
            P.synthesize("안녕", REF, "", "qwen3-tts", ref_seconds=bad)
    assert f.calls == []


def test_wav_reference_length_is_measured(fal):
    f = fal()
    with pytest.raises(ProviderError) as e:
        P.synthesize("안녕", wav(2.0), "", "chatterbox")
    assert e.value.code == "ref_too_short"
    P.synthesize("안녕", wav(3.5), "", "chatterbox")  # 3초 이상이면 호출
    assert f.of("POST")


def test_bad_inputs(fal):
    fal()
    for args in [
        ("", REF, "", "qwen3-tts"),
        ("안녕", b"", "", "qwen3-tts"),
        ("안녕", REF, "", "unknown-model"),
        (None, REF, "", "qwen3-tts"),
        ("안녕", b"plain bytes", "", "qwen3-tts"),
    ]:
        with pytest.raises(ProviderError):
            P.synthesize(*args, ref_seconds=5)


# --- 문장 끊기 ------------------------------------------------------------------


def test_split_text_by_sentences_under_limit():
    s1 = "가" * 200 + "."
    s2 = "나" * 150 + "!"
    s3 = "다" * 50 + "?"
    chunks = P.split_text(f"{s1} {s2} {s3}")
    assert chunks == [s1, f"{s2} {s3}"]
    assert all(len(c) <= P.MAX_CHUNK_CHARS for c in chunks)
    assert P.split_text("짧은 말. 또 짧은 말.") == ["짧은 말. 또 짧은 말."]
    assert P.split_text("") == []


def test_split_text_cuts_overlong_sentence():
    long = ("말이 길어요 " * 100).strip()
    chunks = P.split_text(long)
    assert len(chunks) > 1
    assert all(0 < len(c) <= P.MAX_CHUNK_CHARS for c in chunks)
    assert "".join(chunks).replace(" ", "") == long.replace(" ", "")
    nospace = "가" * 650
    assert [len(c) for c in P.split_text(nospace)] == [300, 300, 50]


# --- Qwen 2단계 -------------------------------------------------------------------


def test_qwen_two_step_bodies_headers_and_cleanup(fal):
    f = fal(audio=[wav(0.2)])
    audio, mime, secs = P.synthesize(
        "밥은 먹었니?", REF, "참조 자막", "qwen3-tts", ref_seconds=11, ref_mime="audio/mpeg", timeout=30
    )
    assert mime == "audio/wav" and audio.startswith(b"RIFF") and secs >= 0
    assert P.wait_for_cleanups(5)

    posts = f.of("POST")
    assert [c["url"] for c in posts] == [
        "https://queue.fal.run/fal-ai/qwen-3-tts/clone-voice/1.7b",
        "https://queue.fal.run/fal-ai/qwen-3-tts/text-to-speech/1.7b",
    ]
    clone, tts = posts[0]["json"], posts[1]["json"]
    assert set(clone) == {"audio_url", "reference_text"}
    assert clone["audio_url"].startswith("data:audio/mpeg;base64,")  # CDN 업로드 없이 직접 싣는다
    assert clone["reference_text"] == "참조 자막"
    assert set(tts) == {"text", "language", "speaker_voice_embedding_file_url", "reference_text"}
    assert tts["language"] == "Korean"
    assert tts["speaker_voice_embedding_file_url"] == EMB_URL
    assert tts["text"] == "밥은 먹었니?"

    # 순서: 복제 제출 → 복제 상태 → 복제 결과 → 합성 제출 → ... → 내려받기 → 삭제
    order = [(c["method"], c["url"]) for c in f.calls]
    i_clone_result = order.index(("GET", "https://queue.fal.run/fal-ai/x/requests/req-1"))
    i_tts_submit = order.index(("POST", "https://queue.fal.run/fal-ai/qwen-3-tts/text-to-speech/1.7b"))
    assert i_clone_result < i_tts_submit
    first_delete = min(i for i, c in enumerate(f.calls) if c["method"] == "DELETE")
    assert all(c["method"] == "DELETE" for c in f.calls[first_delete:])
    assert sorted(deleted_ids(f)) == ["req-1", "req-2"]  # 두 요청 모두 삭제
    assert f.of("DELETE")[0]["url"] == "https://api.fal.ai/v1/models/requests/req-1/payloads"

    # 개인정보 헤더는 모든 fal API 요청에, 키는 CDN 내려받기에 보내지 않는다
    for c in f.calls:
        if "fal.media" in c["url"]:
            assert "Authorization" not in c["headers"]
            continue
        assert c["headers"]["Authorization"] == f"Key {FAKE_KEY}"
        assert c["headers"]["X-Fal-Store-IO"] == "0"
        if c["method"] != "DELETE" and c["method"] != "PUT":
            assert json.loads(c["headers"]["X-Fal-Object-Lifecycle-Preference"]) == {
                "expiration_duration_seconds": 3600
            }
            assert int(c["headers"]["X-Fal-Request-Start-Timeout"]) >= 1
        assert c["timeout"] is not None and c["timeout"] <= P.HTTP_TIMEOUT_SEC


def test_qwen_without_ref_text_omits_reference_text(fal):
    f = fal()
    P.synthesize("응", REF, "", "qwen3-tts", ref_seconds=5)
    assert "reference_text" not in f.of("POST")[0]["json"]
    assert "reference_text" not in f.of("POST")[1]["json"]


def test_long_text_makes_one_request_per_chunk_and_joins_wav(fal):
    f = fal(audio=[wav(0.2)])
    text = ("가" * 89 + ". ") * 3  # 90자 문장 3개 → Qwen 조각 상한 100자라 조각 3개
    audio, mime, _ = P.synthesize(text, REF, "", "qwen3-tts", ref_seconds=5)
    tts_posts = f.of("POST", "text-to-speech")
    assert len(tts_posts) == 3
    assert all(len(c["json"]["text"]) <= P.QWEN_MAX_CHUNK_CHARS for c in tts_posts)
    with wave.open(io.BytesIO(audio), "rb") as w:
        assert w.getnframes() == 3 * int(24000 * 0.2)
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
    assert len(deleted_ids(f)) == 4  # 복제 1 + 합성 3


def test_mpeg_chunks_are_joined(fal):
    fal(audio=[MP3], audio_ct="audio/mpeg")
    audio, mime, _ = P.synthesize(("가" * 200 + ". ") * 2, REF, "", "chatterbox", ref_seconds=5)
    assert mime == "audio/mpeg" and audio == MP3 + MP3


def test_mixed_formats_is_bad_output_and_still_cleans_up(fal):
    f = fal(audio=[wav(0.1)], audio_ct=["audio/wav", "audio/mpeg"])
    with pytest.raises(ProviderError) as e:
        P.synthesize(("가" * 200 + ". ") * 2, REF, "", "chatterbox", ref_seconds=5)
    assert e.value.code == "bad_output"
    assert len(deleted_ids(f)) == 2


def test_mime_from_signature_when_content_type_missing(fal):
    fal(audio=[wav(0.1)], audio_ct=None)
    _, mime, _ = P.synthesize("응", REF, "", "chatterbox", ref_seconds=5)
    assert mime == "audio/wav"


# --- Chatterbox -------------------------------------------------------------------


def test_chatterbox_body(fal):
    f = fal()
    P.synthesize("보고 싶다", REF, "자막은 안 보냄", "chatterbox", ref_seconds=5, ref_mime="audio/mpeg")
    posts = f.of("POST")
    assert [c["url"] for c in posts] == [
        "https://queue.fal.run/fal-ai/chatterbox/text-to-speech/multilingual"
    ]
    body = posts[0]["json"]
    assert set(body) == {"text", "voice", "custom_audio_language"}
    assert body["voice"].startswith("data:audio/mpeg;base64,")
    assert body["custom_audio_language"] == "korean"
    assert deleted_ids(f) == ["req-1"]


# --- 실패·시간 초과·정리 --------------------------------------------------------------


def test_error_status_raises_and_deletes(fal):
    f = fal(status_error="validation_error")
    with pytest.raises(ProviderError) as e:
        P.synthesize("응", REF, "", "qwen3-tts", ref_seconds=5)
    assert e.value.code == "http_error"
    assert deleted_ids(f) == ["req-1"]


def test_result_failure_on_second_step_deletes_both(fal):
    f = fal(fail_on="text-to-speech")
    with pytest.raises(ProviderError):
        P.synthesize("응", REF, "", "qwen3-tts", ref_seconds=5)
    assert sorted(deleted_ids(f)) == ["req-1", "req-2"]


def test_overall_timeout_cancels_and_deletes(fal, monkeypatch):
    f = fal(status_seq=["IN_QUEUE"] + ["IN_PROGRESS"] * 10_000)
    monkeypatch.setattr(P, "_sleep", lambda s: time.sleep(0.01))
    t0 = time.monotonic()
    with pytest.raises(ProviderError) as e:
        P.synthesize("응", REF, "", "chatterbox", ref_seconds=5, timeout=0.2)
    assert e.value.code == "timeout"
    assert time.monotonic() - t0 < 3
    assert P.wait_for_cleanups(5)
    assert len(f.of("PUT")) == 1 and f.of("PUT")[0]["url"].endswith("/cancel")  # 끝나지 않은 요청 취소
    # 순서: 취소 → 상태 확인(끝남) → 삭제
    seq = [(c["method"], c["url"].rsplit("/", 1)[-1]) for c in f.calls]
    i_put = seq.index(("PUT", "cancel"))
    i_del = max(i for i, s in enumerate(seq) if s[0] == "DELETE")
    assert ("GET", "status") in seq[i_put:i_del]
    assert deleted_ids(f) == ["req-1"]


def test_cancelled_request_never_finishes_logs_not_deleted(fal, caplog):
    f = fal(status_seq=["IN_PROGRESS"] * 10_000, cancel_completes=False)
    with caplog.at_level(logging.WARNING, logger="yeoun.voice.provider"):
        with pytest.raises(ProviderError) as e:
            P.synthesize("응", REF, "", "chatterbox", ref_seconds=5, timeout=0.2)
        assert P.wait_for_cleanups(5)
    assert e.value.code == "timeout"
    assert len(f.of("PUT")) == 1
    assert len(f.of("GET", "/status")) >= 2  # 취소 뒤에도 상태를 확인했다
    assert deleted_ids(f) == ["req-1"]  # 한 번은 시도
    assert "fal_payload_not_deleted status=400 finished=no" in caplog.text


def test_http_timeout_becomes_provider_error(fal):
    f = fal(raise_timeout_on="/status")
    with pytest.raises(ProviderError) as e:
        P.synthesize("응", REF, "", "chatterbox", ref_seconds=5)
    assert e.value.code == "timeout"
    assert deleted_ids(f) == ["req-1"]


def test_delete_failure_does_not_raise(fal, caplog):
    fal(delete_status=500)
    with caplog.at_level(logging.WARNING, logger="yeoun.voice.provider"):
        audio, mime, _ = P.synthesize("응", REF, "", "chatterbox", ref_seconds=5)
        assert P.wait_for_cleanups(5)
    assert audio
    assert "fal_payload_not_deleted status=500 finished=yes" in caplog.text


# --- 정리는 결과를 돌려준 뒤 뒤에서 ----------------------------------------------------


class SlowDelete:
    """삭제·취소·정리 상태 확인만 느린 FakeFal 감싸기."""

    def __init__(self, fake: FakeFal, delay: float, exc: BaseException | None = None):
        self.fake, self.delay, self.exc = fake, delay, exc
        self.done = threading.Event()

    def __call__(self, method, url, **kw):
        if method in ("DELETE", "PUT"):
            time.sleep(self.delay)
            if self.exc is not None:
                raise self.exc
        r = self.fake(method, url, **kw)
        if method == "DELETE":
            self.done.set()
        return r


def test_slow_delete_does_not_delay_result(fal, monkeypatch):
    f = fal()
    slow = SlowDelete(f, delay=1.0)
    monkeypatch.setattr(P.httpx, "request", slow)
    t0 = time.monotonic()
    audio, mime, secs = P.synthesize("응", REF, "", "chatterbox", ref_seconds=5, timeout=0.8)
    assert audio and time.monotonic() - t0 < 0.8  # 삭제(1초)를 기다리지 않고 제한(0.8초) 안에 돌아옴
    assert not slow.done.is_set()
    assert P.wait_for_cleanups(5)  # 정리 스레드 join
    assert slow.done.is_set()
    assert deleted_ids(f) == ["req-1"]


def test_early_failure_returns_without_waiting_for_cleanup(fal, monkeypatch):
    f = fal(status_error="validation_error", cancel_completes=False)
    monkeypatch.setattr(P, "CLEANUP_TIMEOUT_SEC", 2.0)  # 정리 상태 확인이 2초 걸려도
    t0 = time.monotonic()
    with pytest.raises(ProviderError):
        P.synthesize("응", REF, "", "chatterbox", ref_seconds=5)
    assert time.monotonic() - t0 < 0.5  # 호출자는 바로 오류를 받는다
    assert P.wait_for_cleanups(5)
    assert deleted_ids(f) == ["req-1"]


def test_wait_cleanup_true_cleans_before_returning(fal, monkeypatch):
    f = fal()
    slow = SlowDelete(f, delay=0.2)
    monkeypatch.setattr(P.httpx, "request", slow)
    P.synthesize("응", REF, "", "chatterbox", ref_seconds=5, wait_cleanup=True)
    assert slow.done.is_set()  # 돌려받을 때 이미 삭제가 끝났다
    assert [c["method"] for c in f.calls][-1] == "DELETE"


def test_cleanup_exceptions_do_not_escape(fal, monkeypatch, caplog):
    f = fal(status_seq=["IN_PROGRESS"] * 10_000)
    for exc in (RuntimeError("x"), KeyboardInterrupt(), SystemExit(1)):
        slow = SlowDelete(f, delay=0.0, exc=exc)
        monkeypatch.setattr(P.httpx, "request", slow)
        with caplog.at_level(logging.WARNING, logger="yeoun.voice.provider"):
            with pytest.raises(ProviderError):
                P.synthesize("응", REF, "", "chatterbox", ref_seconds=5, timeout=0.05)
            assert P.wait_for_cleanups(5)
        # 동기 정리에서도 새지 않는다
        with pytest.raises(ProviderError):
            P.synthesize("응", REF, "", "chatterbox", ref_seconds=5, timeout=0.05, wait_cleanup=True)


def test_cleanup_crash_is_logged_not_raised(fal, monkeypatch, caplog):
    fal()

    def boom(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(P._FalJob, "cleanup", boom)
    with caplog.at_level(logging.WARNING, logger="yeoun.voice.provider"):
        audio, _, _ = P.synthesize("응", REF, "", "chatterbox", ref_seconds=5)
        assert P.wait_for_cleanups(5)
        P.synthesize("응", REF, "", "chatterbox", ref_seconds=5, wait_cleanup=True)
    assert audio
    assert caplog.text.count("fal_cleanup_crashed error=KeyboardInterrupt") == 2


# --- 응답 주소의 호스트 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "https://evil.example/requests/req-1/status",
        "http://queue.fal.run/requests/req-1/status",
        "https://queue.fal.run.evil.example/requests/req-1/status",
        "https://user@queue.fal.run/requests/req-1/status",
        "https://queue.fal.run:8443/requests/req-1/status",
    ],
)
def test_queue_urls_must_be_queue_host(fal, monkeypatch, bad):
    f = fal()

    def wrapped(method, url, **kw):
        r = f(method, url, **kw)
        if method == "POST" and url.startswith(P.FAL_QUEUE_BASE):
            data = r.json()
            data["status_url"] = bad
            data["cancel_url"] = bad.replace("/status", "/cancel")
            return httpx.Response(200, json=data)
        return r

    monkeypatch.setattr(P.httpx, "request", wrapped)
    with pytest.raises(ProviderError) as e:
        P.synthesize("응", REF, "", "chatterbox", ref_seconds=5)
    assert e.value.code == "bad_output"
    assert P.wait_for_cleanups(5)
    hosts = {c["url"].split("/")[2] for c in f.calls}
    assert hosts <= {"queue.fal.run", "api.fal.ai"}  # 키가 다른 호스트로 나가지 않았다
    assert not any(c["url"] == bad or c["url"].startswith(bad.split("/requests")[0] + "/") for c in f.calls)
    assert deleted_ids(f) == ["req-1"]  # 삭제는 상수 주소로 시도


# --- 참조 길이 상한 ------------------------------------------------------------------


def test_reference_over_300s_is_rejected(fal):
    f = fal()
    for model in ("qwen3-tts", "chatterbox"):
        with pytest.raises(ProviderError) as e:
            P.synthesize("응", REF, "", model, ref_seconds=300.1)
        assert e.value.code == "bad_input"
    assert f.calls == []
    P.synthesize("응", REF, "", "chatterbox", ref_seconds=300)  # 300초까지는 된다
    assert f.of("POST")


def test_qwen_chunks_are_at_most_100_chars(fal):
    f = fal()
    P.synthesize(("나" * 60 + ". ") * 4, REF, "", "qwen3-tts", ref_seconds=5)
    texts = [c["json"]["text"] for c in f.of("POST", "text-to-speech")]
    assert len(texts) == 4 and all(len(t) <= 100 for t in texts)
    assert P.QWEN_MAX_CHUNK_CHARS == 100 and P.MAX_CHUNK_CHARS == 300


def test_split_text_does_not_send_punctuation_only_chunks():
    chunks = P.split_text("가" * 200 + ".", 100)
    assert all(any(ch.isalnum() for ch in c) for c in chunks)
    assert "".join(chunks).rstrip(".") == "가" * 200  # 소리 나는 글자는 빠지지 않는다


# --- 내려받은 음성 형식 교차 확인 ----------------------------------------------------


def test_html_with_audio_content_type_is_bad_output(fal):
    f = fal(audio=[b"<!DOCTYPE html><html>error</html>"], audio_ct="audio/mpeg")
    with pytest.raises(ProviderError) as e:
        P.synthesize("응", REF, "", "chatterbox", ref_seconds=5)
    assert e.value.code == "bad_output"
    assert deleted_ids(f) == ["req-1"]


def test_declared_type_must_match_signature(fal):
    fal(audio=[wav(0.1)], audio_ct="audio/mpeg")
    with pytest.raises(ProviderError) as e:
        P.synthesize("응", REF, "", "chatterbox", ref_seconds=5)
    assert e.value.code == "bad_output"


def test_sniff_mime():
    assert P.sniff_mime(wav(0.01)) == "audio/wav"
    assert P.sniff_mime(MP3) == "audio/mpeg"
    assert P.sniff_mime(b"ID3\x04") == "audio/mpeg"
    assert P.sniff_mime(b"\xff\xf1\x50\x80") is None  # AAC ADTS(레이어 00)
    assert P.sniff_mime(b"<html>") is None
    assert P.sniff_mime(b"") is None


# --- 키 없음·mock ------------------------------------------------------------------


def no_network(*a, **k):
    raise AssertionError("네트워크를 부르면 안 된다")


def test_no_key_is_not_configured_and_never_silent(monkeypatch):
    monkeypatch.delenv(P.ENV_FAL_KEY, raising=False)
    monkeypatch.setattr(P.httpx, "request", no_network)
    with pytest.raises(ProviderError) as e:
        P.synthesize("안녕", REF, "", "qwen3-tts", ref_seconds=5)
    assert e.value.code == "not_configured"
    with pytest.raises(ProviderError) as e:
        P.synthesize("안녕", REF, "", "qwen3-tts", ref_seconds=5, provider="fal")
    assert e.value.code == "not_configured"
    with pytest.raises(ProviderError) as e:
        P.synthesize("안녕", REF, "", "qwen3-tts", ref_seconds=5, provider="other")
    assert e.value.code == "bad_input"


def test_mock_provider_only_when_chosen(monkeypatch):
    monkeypatch.setenv(P.ENV_FAL_KEY, FAKE_KEY)  # 키가 있어도 mock 을 고르면 네트워크 없음
    monkeypatch.setattr(P.httpx, "request", no_network)
    audio, mime, secs = P.synthesize("안녕", REF, "", "qwen3-tts", ref_seconds=5, provider="mock")
    assert mime == "audio/wav"
    with wave.open(io.BytesIO(audio), "rb") as w:
        assert w.getnframes() > 0
    with pytest.raises(ProviderError):  # mock 도 3초 미만은 거절
        P.synthesize("안녕", REF, "", "qwen3-tts", ref_seconds=1, provider="mock")


# --- 로그 -----------------------------------------------------------------------


def test_logs_have_no_text_key_or_urls(fal, caplog):
    fal(delete_status=404)
    with caplog.at_level(logging.DEBUG):
        P.synthesize("비밀문장입니다", REF, "비밀자막", "qwen3-tts", ref_seconds=5)
        try:
            P.synthesize("비밀문장입니다", REF, "비밀자막", "qwen3-tts", ref_seconds=1)
        except ProviderError as e:
            assert "비밀" not in str(e)
    assert caplog.records
    for secret in ("비밀문장", "비밀자막", FAKE_KEY, "http", "secret_embedding", "fal.media"):
        assert secret not in caplog.text
