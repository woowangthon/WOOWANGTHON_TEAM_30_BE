"""ffmpeg/ffprobe 도우미. 셸을 거치지 않고 인자 목록으로만 호출한다."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


def _run(args: list[str], timeout: float = 600) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise MediaError("ffmpeg_missing", "ffmpeg가 설치되어 있지 않습니다") from e
    except subprocess.TimeoutExpired as e:
        raise MediaError("media_timeout") from e


@dataclass
class ProbeResult:
    duration: float
    has_audio: bool
    creation_time: str | None


def probe(path: Path) -> ProbeResult:
    r = _run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        timeout=60,
    )
    if r.returncode != 0:
        raise MediaError("unreadable_media")
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError as e:
        raise MediaError("unreadable_media") from e
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    try:
        duration = float(fmt.get("duration") or 0)
    except ValueError:
        duration = 0.0
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    for s in streams:
        for k, v in (s.get("tags") or {}).items():
            tags.setdefault(k.lower(), v)
    creation = tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate") or tags.get("date")
    return ProbeResult(duration=duration, has_audio=has_audio, creation_time=creation)


def to_wav16k(src: Path, dst: Path) -> None:
    """정규화: 영상이면 오디오만, 16kHz mono PCM WAV."""
    r = _run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-ac", "1",
              "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])  # fmt: skip
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 100:
        raise MediaError("normalize_failed")


def encode_for_upload(
    src: Path, dst: Path, start: float | None = None, duration: float | None = None
) -> None:
    """외부 STT로 보낼 작은 파일 (mp3 16kHz mono 48kbps)."""
    args = [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(dst)]
    r = _run(args)
    if r.returncode != 0 or not dst.exists():
        raise MediaError("encode_failed")


def cut_clip(wav: Path, start: float, end: float, dst: Path) -> None:
    """원본 구간을 그대로 잘라 재생용 mp3로 만든다 (내용을 바꾸지 않는다: 소리 크기만 살짝 맞춤)."""
    dur = max(0.1, end - start)
    r = _run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
              "-i", str(wav), "-af", "afade=t=in:d=0.05,dynaudnorm=f=250:g=15", "-ac", "1", "-ar", "24000",
              "-c:a", "libmp3lame", "-b:a", "64k", str(dst)], timeout=120)  # fmt: skip
    if r.returncode != 0 or not dst.exists():
        raise MediaError("clip_failed")


def transcode_audio_for_playback(src: Path, dst: Path) -> None:
    r = _run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-ac", "1",
              "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "64k", str(dst)], timeout=300)  # fmt: skip
    if r.returncode != 0 or not dst.exists():
        raise MediaError("clip_failed")


_SIL_START = re.compile(r"silence_start: (-?[\d.]+)")
_SIL_END = re.compile(r"silence_end: (-?[\d.]+)")


def detect_speech(
    wav: Path, duration: float, noise_db: int = -35, min_silence: float = 0.6
) -> list[tuple[float, float]]:
    """무음 구간을 찾아 말소리 구간 목록을 돌려준다 (AI 없이 쓰는 규칙 기반 분할)."""
    r = _run([FFMPEG, "-nostdin", "-hide_banner", "-i", str(wav), "-af",
              f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"], timeout=600)  # fmt: skip
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in r.stderr.splitlines():
        m = _SIL_START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _SIL_END.search(line)
        if m and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:
        silences.append((start, duration))
    speech: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in silences:
        if s - cursor >= 0.3:
            speech.append((cursor, s))
        cursor = e
    if duration - cursor >= 0.3:
        speech.append((cursor, duration))
    return speech


def make_test_tone(dst: Path, seconds: float = 6.0, pattern: str = "speech") -> None:
    """테스트·placeholder용 합성 소리 (실제 사람 목소리 아님)."""
    if pattern == "speech":
        # 말소리처럼 끊기는 톤: 1.5초 소리 + 0.8초 무음 반복
        expr = "0.3*sin(2*PI*220*t)*lt(mod(t\\,2.3)\\,1.5)"
    else:
        expr = "0.2*sin(2*PI*330*t)"
    r = _run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
              f"aevalsrc={expr}:s=16000:d={seconds}", "-ac", "1", str(dst)], timeout=60)  # fmt: skip
    if r.returncode != 0:
        raise MediaError("tone_failed")
