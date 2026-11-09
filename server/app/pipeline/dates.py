"""자료 날짜 알아내기: 파일명 → 메타데이터(촬영·녹음 시각) → 올린 날.

예) 삼성 통화 녹음 '통화 녹음 엄마_230512_143005.m4a', 카메라 '20230512_143005.mp4',
    아이폰 영상은 파일 안의 creation_time.
"""

from __future__ import annotations

import datetime as dt
import re

_FULL = re.compile(r"(?<!\d)(19[9]\d|20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])")
_SHORT = re.compile(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[_-]\d{4,6}(?!\d)")


def _valid(y: int, m: int, d: int, today: dt.date) -> dt.date | None:
    try:
        date = dt.date(y, m, d)
    except ValueError:
        return None
    if date.year < 1990 or date > today:
        return None
    return date


def date_from_filename(name: str, today: dt.date | None = None) -> dt.date | None:
    today = today or dt.date.today()
    m = _FULL.search(name)
    if m:
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
        if d:
            return d
    m = _SHORT.search(name)
    if m:
        return _valid(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
    return None


def date_from_metadata(value: str | None, today: dt.date | None = None) -> dt.date | None:
    if not value:
        return None
    today = today or dt.date.today()
    m = re.match(r"(\d{4})[-:](\d{2})[-:](\d{2})", value.strip())
    if not m:
        return None
    d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
    # 1970·2000년 1월 1일 같은 기본값은 믿지 않는다
    if d and (d.month, d.day) == (1, 1) and d.year in (1970, 2000, 2001):
        return None
    return d


def guess_origin(filename: str, kind: str, ext: str) -> str:
    low = filename.lower()
    if kind == "video":
        return "video"
    if "통화" in filename or "call" in low or ("recording" in low and "voice" not in low):
        return "call"
    if any(k in low for k in ("voice", "음성", "ptt", "kakao", "카톡", "메시지")) or ext in (
        "amr",
        "opus",
        "ogg",
    ):
        return "voice_message"
    return "other"
