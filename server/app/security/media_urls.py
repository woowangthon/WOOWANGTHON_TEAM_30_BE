"""재생·사진용 서명 URL. 짧게 만료되며, 쿠키 없이도 <audio>/<img>가 불러올 수 있다."""

from __future__ import annotations

import time

from app.config import get_settings
from app.security.crypto import hmac_sign, hmac_verify


def _message(kind: str, obj_id: str, exp: int) -> str:
    return f"media:{kind}:{obj_id}:{exp}"


def media_url(kind: str, obj_id: str, ttl: int | None = None) -> str:
    exp = int(time.time()) + (ttl or get_settings().media_url_ttl_sec)
    return f"/api/media/{kind}/{obj_id}?exp={exp}&sig={hmac_sign(_message(kind, obj_id, exp))}"


def verify(kind: str, obj_id: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    return hmac_verify(_message(kind, obj_id, exp), sig)
