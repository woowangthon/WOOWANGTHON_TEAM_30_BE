"""대화 답장 합성(app/voice/reply.py) 테스트.

실제 네트워크·DB·저장소를 쓰지 않는다: 클립 목록·음성 읽기·합성 공급자를 가짜로 바꿔 끼운다.
provider.py 가 아직 없어도 돌도록, 기본 경로 테스트는 sys.modules 에 가짜 app.voice.provider 를 넣는다.
"""

from __future__ import annotations

import base64
import logging
import sys
import threading
import types
from types import SimpleNamespace

from app.voice import reply
from app.voice.reply import (
    DEFAULT_MODEL,
    ENV_FAL_KEY,
    ENV_SWITCH,
    VOICE_REPLY_TIMEOUT_SEC,
    join_mp3,
    synth_for_reply,
)

SPACE = SimpleNamespace(id="space-1")
DB = object()
FAKE_KEY = "test-not-a-real-key"  # 테스트 전용 가짜 값


def clip(cid: str, dur: float, text: str = "자막", ready: bool = True):
    return SimpleNamespace(
        id=cid,
        start_sec=0.0,
        end_sec=dur,
        text=text,
        audio_key=f"spaces/space-1/assets/a/clips/{cid}.mp3" if ready else None,
        audio_status="ready" if ready else "missing",
    )


def rows_of(*clips):
    return lambda db, space_id: [(c, SimpleNamespace(id="a")) for c in clips]


def audio_of(space, key):
    return b"MP3:" + key.rsplit("/", 1)[-1].encode()


class FakeSynth:
    def __init__(self, result=(b"RIFFfake", "audio/wav", 0.1), exc: Exception | None = None):
        self.result = result
        self.exc = exc
        self.calls: list[tuple] = []
        self.kwargs: list[dict] = []

    def __call__(self, text, ref_audio, ref_text, model, **kw):
        self.calls.append((text, ref_audio, ref_text, model))
        self.kwargs.append(kw)
        if self.exc:
            raise self.exc
        return self.result


def on(monkeypatch):
    monkeypatch.setenv(ENV_SWITCH, "on")
    monkeypatch.setenv(ENV_FAL_KEY, FAKE_KEY)


def call(**kw):
    kw.setdefault("clips_loader", rows_of(clip("c1", 6), clip("c2", 5)))
    kw.setdefault("load_audio", audio_of)
    args = kw.pop("args", (DB, SPACE, "밥은 먹었니", []))
    return synth_for_reply(*args, **kw)


# --- 켜짐·키 -------------------------------------------------------------------


def test_off_returns_none_without_calling_provider(monkeypatch):
    monkeypatch.delenv(ENV_SWITCH, raising=False)
    monkeypatch.setenv(ENV_FAL_KEY, FAKE_KEY)
    s = FakeSynth()
    assert call(synthesize=s) is None
    monkeypatch.setenv(ENV_SWITCH, "off")
    assert call(synthesize=s) is None
    assert s.calls == []


def test_no_key_returns_none(monkeypatch):
    monkeypatch.setenv(ENV_SWITCH, "on")
    monkeypatch.delenv(ENV_FAL_KEY, raising=False)
    s = FakeSynth()
    assert call(synthesize=s) is None
    monkeypatch.setenv(ENV_FAL_KEY, "   ")
    assert call(synthesize=s) is None
    assert s.calls == []


# --- 성공 ----------------------------------------------------------------------


def test_success_returns_data_url(monkeypatch):
    on(monkeypatch)
    s = FakeSynth(result=(b"\x00\x01audio", "audio/mpeg", 0.2))
    url = call(synthesize=s)
    assert url is not None and url.startswith("data:audio/mpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x00\x01audio"
    text, ref_audio, ref_text, model = s.calls[0]
    assert text == "밥은 먹었니"
    assert ref_audio == b"MP3:c1.mp3MP3:c2.mp3"  # 고른 클립을 이어 붙인 참조
    assert ref_text == "자막 자막"
    assert model == DEFAULT_MODEL
    kw = s.kwargs[0]
    assert kw["ref_seconds"] == 11  # 6 + 5초
    assert kw["ref_mime"] == "audio/mpeg"
    assert 0 < kw["timeout"] <= VOICE_REPLY_TIMEOUT_SEC  # 남은 시간을 공급자에게 넘긴다


def test_source_ids_are_preferred_reference(monkeypatch):
    on(monkeypatch)
    s = FakeSynth()
    loader = rows_of(clip("a", 6), clip("b", 6), clip("src", 4, text="근거 자막"))
    assert call(args=(DB, SPACE, "응", ["src"]), clips_loader=loader, synthesize=s)
    _, ref_audio, ref_text, _ = s.calls[0]
    assert ref_audio.startswith(b"MP3:src.mp3")
    assert ref_text.startswith("근거 자막")


def test_clips_without_ready_audio_are_not_used(monkeypatch):
    on(monkeypatch)
    s = FakeSynth()
    loader = rows_of(clip("noaudio", 8, ready=False), clip("ok", 4))
    assert call(clips_loader=loader, synthesize=s)
    assert s.calls[0][1] == b"MP3:ok.mp3"


def test_default_path_uses_provider_module(monkeypatch):
    """provider.py 가 없어도: sys.modules 의 app.voice.provider.synthesize 를 부른다."""
    on(monkeypatch)
    seen = {}

    def fake_synthesize(text, ref_audio, ref_text, model, **kw):
        seen["args"] = (text, ref_audio, ref_text, model)
        seen["kw"] = kw
        return b"ok", "audio/wav", 0.0

    mod = types.ModuleType("app.voice.provider")
    mod.synthesize = fake_synthesize  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.voice.provider", mod)
    url = call()
    assert url == "data:audio/wav;base64," + base64.b64encode(b"ok").decode()
    assert seen["args"][3] == DEFAULT_MODEL
    assert seen["kw"]["provider"] == "fal"  # 그분 답장은 언제나 실제 공급자(mock 금지)
    # 누가 mock 을 넘겨도 기본 경로는 fal 로 바꾼다
    reply._default_synthesize("a", b"b", "c", DEFAULT_MODEL, provider="mock")
    assert seen["kw"]["provider"] == "fal"


def test_real_provider_without_key_never_returns_silence(monkeypatch):
    """reply 가 키를 확인한 뒤 키가 사라져도, 실제 provider 는 무음 대신 not_configured → None."""
    on(monkeypatch)
    real = __import__("app.voice.provider", fromlist=["synthesize"])
    monkeypatch.setitem(sys.modules, "app.voice.provider", real)

    def loader(db, space_id):
        monkeypatch.delenv(ENV_FAL_KEY)  # 클립을 고르는 사이 키가 사라짐
        return [(clip("c1", 6), None), (clip("c2", 5), None)]

    assert call(clips_loader=loader) is None


def test_base_exception_in_provider_thread_does_not_escape(monkeypatch):
    on(monkeypatch)
    for exc in (KeyboardInterrupt(), SystemExit(1), GeneratorExit()):
        assert call(synthesize=FakeSynth(exc=exc)) is None


def test_keyboard_interrupt_on_main_thread_is_not_swallowed(monkeypatch):
    on(monkeypatch)

    def interrupted(db, space_id):
        raise KeyboardInterrupt

    try:
        call(clips_loader=interrupted, synthesize=FakeSynth())
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("메인 스레드의 KeyboardInterrupt 는 삼키지 않는다")


# --- 실패하면 None -------------------------------------------------------------


def test_reference_under_3s_returns_none(monkeypatch):
    on(monkeypatch)
    s = FakeSynth()
    assert call(clips_loader=rows_of(clip("a", 1.0), clip("b", 1.5)), synthesize=s) is None
    assert call(clips_loader=rows_of(), synthesize=s) is None
    assert s.calls == []


def test_provider_error_returns_none(monkeypatch):
    on(monkeypatch)

    class ProviderError(Exception):
        def __init__(self, code):
            super().__init__(code)
            self.code = code

    assert call(synthesize=FakeSynth(exc=ProviderError("http_error"))) is None
    assert call(synthesize=FakeSynth(exc=RuntimeError("boom"))) is None


def test_provider_timeout_returns_none_quickly(monkeypatch):
    on(monkeypatch)
    release = threading.Event()

    def slow(text, ref_audio, ref_text, model, **kw):
        release.wait(5)
        return b"late", "audio/wav", 5.0

    import time

    t0 = time.monotonic()
    try:
        assert call(synthesize=slow, timeout_sec=0.3) is None
    finally:
        release.set()
    assert time.monotonic() - t0 < 2.0


def test_bad_provider_output_returns_none(monkeypatch):
    on(monkeypatch)
    for bad in [
        None,
        "x",
        (b"", "audio/wav", 0),
        (b"a", "text/html", 0),
        (b"a", None, 0),
        (b"a",),
        ("a", "audio/wav", 0),
    ]:
        assert call(synthesize=FakeSynth(result=bad)) is None, bad


def test_storage_failure_returns_none(monkeypatch):
    on(monkeypatch)

    def broken(space, key):
        raise KeyError(key)

    assert call(load_audio=broken, synthesize=FakeSynth()) is None
    assert call(load_audio=lambda s, k: b"", synthesize=FakeSynth()) is None


def test_clips_loader_failure_returns_none(monkeypatch):
    on(monkeypatch)

    def broken(db, space_id):
        raise RuntimeError("db down")

    assert call(clips_loader=broken, synthesize=FakeSynth()) is None


def test_weird_arguments_never_raise(monkeypatch):
    on(monkeypatch)
    s = FakeSynth()
    weird = [
        (None, None, None, None),
        (DB, None, "안녕", []),
        (DB, SimpleNamespace(id=None), "안녕", []),
        (DB, SPACE, None, []),
        (DB, SPACE, 123, []),
        (DB, SPACE, "   ", []),
        (None, SPACE, "안녕", []),
        (DB, "space-1", "안녕", []),
        (DB, SPACE, "안녕", None),
        (DB, SPACE, "안녕", "c1"),
        (DB, SPACE, "안녕", 42),
        (DB, SPACE, "안녕", [None, 3, "c2"]),
    ]
    for args in weird:
        out = call(args=args, synthesize=s)
        assert out is None or out.startswith("data:audio/"), args
    # 클립 행 모양이 이상해도 던지지 않는다
    assert (
        call(clips_loader=lambda db, sid: [None, 3, ("x",), (SimpleNamespace(id=1),)], synthesize=s) is None
    )
    assert call(clips_loader=lambda db, sid: None, synthesize=s) is None


def test_long_text_is_trimmed(monkeypatch):
    on(monkeypatch)
    s = FakeSynth()
    assert call(args=(DB, SPACE, "가" * 1000, []), synthesize=s)
    assert len(s.calls[0][0]) == reply.MAX_TEXT_CHARS


# --- 로그에 내용·자막·파일명·키가 남지 않는다 -----------------------------------


def test_logs_do_not_contain_text_subtitles_keys_or_filenames(monkeypatch):
    on(monkeypatch)
    records: list[logging.LogRecord] = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record)

    lg = logging.getLogger("yeoun.voice")
    h = H(level=logging.DEBUG)
    old = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    try:
        loader = rows_of(clip("secretclip", 6, text="비밀자막"), clip("c2", 5, text="비밀자막2"))
        call(args=(DB, SPACE, "비밀문장", []), clips_loader=loader, synthesize=FakeSynth())
        call(
            args=(DB, SPACE, "비밀문장", []),
            clips_loader=loader,
            synthesize=FakeSynth(exc=RuntimeError("비밀문장")),
        )
        call(args=(DB, SPACE, "비밀문장", []), clips_loader=rows_of(clip("secretclip", 1, text="비밀자막")))
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)
    assert records, "결과 코드는 남아야 한다"
    joined = "\n".join(r.getMessage() for r in records)
    for secret in ("비밀문장", "비밀자막", "secretclip", ".mp3", FAKE_KEY):
        assert secret not in joined


# --- 기타 ----------------------------------------------------------------------


def test_timeout_constant():
    assert 0 < VOICE_REPLY_TIMEOUT_SEC <= 30


def test_join_mp3_strips_inner_tags():
    def id3v2(body: bytes) -> bytes:
        n = len(body)
        size = bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])
        return b"ID3\x04\x00\x00" + size + body

    id3v1 = b"TAG" + b"\x00" * 125
    a = id3v2(b"hdrA") + b"FRAMES_A" + id3v1
    b = id3v2(b"hdrB-longer") + b"FRAMES_B" + id3v1
    out = join_mp3([a, b])
    assert out == id3v2(b"hdrA") + b"FRAMES_A" + b"FRAMES_B" + id3v1
    assert join_mp3([b"x"]) == b"x"
    assert join_mp3([]) == b""


# MPEG-2 Layer III, 24kHz, 64kbps, 모노, CRC 없음 (cut_clip 설정과 같음): 프레임 길이 72*64000/24000 = 192
_HDR = bytes([0xFF, 0xF3, 0x84, 0xC0])


def _frame(fill: bytes = b"\x00") -> bytes:
    return _HDR + fill * 188


def _info_frame(tag: bytes = b"Info") -> bytes:
    body = b"\x00" * 9 + tag  # 사이드 정보 9바이트 뒤에 태그
    return _HDR + body + b"\x00" * (188 - len(body))


def test_join_mp3_drops_xing_info_header_frames():
    a = _info_frame(b"Info") + _frame(b"\x11")
    b = _info_frame(b"Xing") + _frame(b"\x22") + _frame(b"\x33")
    out = join_mp3([a, b])
    assert out == _frame(b"\x11") + _frame(b"\x22") + _frame(b"\x33")
    assert b"Info" not in out and b"Xing" not in out
    assert len(out) % 192 == 0


def test_join_mp3_keeps_ordinary_frames_and_single_part():
    a = _frame(b"\x11")
    b = _frame(b"\x22")
    assert join_mp3([a, b]) == a + b
    single = _info_frame() + _frame()
    assert join_mp3([single]) == single  # 하나면 손대지 않는다
