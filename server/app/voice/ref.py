"""참조 클립 고르기: 그분으로 확인된 클립 중 음성 합성의 '참조 음성'으로 쓸 것을 고른다.

DB 없이 입력·출력만 다루는 순수 함수다. FE 담당과 같은 기준 문장을 쓴다:

    참조 클립 기준: 자막이 있는 것을 우선하고, 길이 3~15초인 것을 우선하며,
    합계 10~15초를 목표로 고른다. 합계가 3초 미만이면 합성 불가다.

고르는 순서(결정적 알고리즘):
    ① 길이가 0 이하인 후보는 뺀다. (길이가 숫자가 아니거나 무한대여도 뺀다)
    ② (우선 후보 여부 → 자막 있음 → 길이 3초 이상 15초 이하) 순의 우선순위로 안정 정렬한다.
       같은 순위끼리는 입력 순서를 유지한다. 우선 후보가 없으면 첫 기준은 모두 같아 생략과 같다.
    ③ 앞에서부터 하나씩 더하되, 더했을 때 합계가 15초를 넘으면 그 후보는 건너뛴다.
       단, 아직 아무것도 고르지 않았다면 15초를 넘어도 그 하나는 고른다.
    ④ 합계가 10초 이상이 되면 멈춘다.
    ⑤ 고른 목록, 합계 길이(초), 합성 가능 여부(합계 3초 이상)를 돌려준다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

MIN_TOTAL_SEC = 3.0  # 합계가 이보다 짧으면 합성 불가
TARGET_MIN_SEC = 10.0  # 합계가 이 이상이 되면 멈춤
TARGET_MAX_SEC = 15.0  # 더했을 때 이 값을 넘으면 건너뜀(첫 후보 제외)
CLIP_MIN_SEC = 3.0  # 클립 하나의 선호 길이 하한
CLIP_MAX_SEC = 15.0  # 클립 하나의 선호 길이 상한


@dataclass(frozen=True)
class RefCandidate:
    """참조 후보 클립 하나. id 는 clip_id, duration 은 초, has_text 는 자막 유무."""

    id: str
    duration: float
    has_text: bool
    preferred: bool = False  # BE: 답장의 근거 녹음(source_ids)에 든 클립


@dataclass(frozen=True)
class RefPick:
    clips: tuple[RefCandidate, ...]
    total_sec: float
    usable: bool  # 합계 MIN_TOTAL_SEC 이상이면 True

    @property
    def ids(self) -> list[str]:
        return [c.id for c in self.clips]


def _valid_duration(d: object) -> float | None:
    try:
        v = float(d)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v) or v <= 0:
        return None
    return v


def pick_reference(
    candidates: Iterable[RefCandidate], preferred_ids: Iterable[str] | None = None
) -> RefPick:
    """참조 클립을 고른다. preferred_ids 를 주면 그 id 의 후보를 우선 후보로 본다(후보의 preferred 와 OR)."""
    pref = {str(i) for i in (preferred_ids or [])}

    # ① 길이 0 이하 제외
    valid: list[tuple[RefCandidate, float]] = []
    for c in candidates:
        d = _valid_duration(c.duration)
        if d is not None:
            valid.append((c, d))

    # ② 안정 정렬 (False 가 앞이므로 '아님'을 키로 쓴다)
    def rank(item: tuple[RefCandidate, float]) -> tuple[bool, bool, bool]:
        c, d = item
        is_pref = bool(c.preferred) or c.id in pref
        in_range = CLIP_MIN_SEC <= d <= CLIP_MAX_SEC
        return (not is_pref, not bool(c.has_text), not in_range)

    ordered = sorted(valid, key=rank)

    # ③·④ 더하기
    chosen: list[RefCandidate] = []
    total = 0.0
    for c, d in ordered:
        if chosen and total + d > TARGET_MAX_SEC:
            continue
        chosen.append(c)
        total += d
        if total >= TARGET_MIN_SEC:
            break

    # ⑤
    return RefPick(clips=tuple(chosen), total_sec=round(total, 3), usable=total >= MIN_TOTAL_SEC)
