"""공간별 검색 색인 캐시 (단계 4에서 채움)."""

from __future__ import annotations

_CACHE: dict[str, object] = {}


def drop_space_index(space_id: str) -> None:
    _CACHE.pop(space_id, None)
