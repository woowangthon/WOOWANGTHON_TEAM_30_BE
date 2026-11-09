"""서명 URL로만 열리는 재생·사진 경로. 복호화해서 내려주고, Range 요청을 지원한다(사파리 재생용)."""

from __future__ import annotations

import re
import time

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Asset, Clip, Space
from app.security.media_urls import verify
from app.storage import StorageNotFound, blobstore

router = APIRouter(tags=["media"])

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def _serve(data: bytes, content_type: str, request: Request, exp: int) -> Response:
    max_age = max(0, exp - int(time.time()))
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": f"private, max-age={max_age}",
        "Content-Disposition": "inline",
    }
    rng = request.headers.get("range")
    total = len(data)
    if rng:
        m = _RANGE.match(rng.strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else total - 1
            else:
                start = max(0, total - int(m.group(2)))
                end = total - 1
            end = min(end, total - 1)
            if start > end or start >= total:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{total}"})
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
            return Response(data[start : end + 1], status_code=206, media_type=content_type, headers=headers)
    return Response(data, media_type=content_type, headers=headers)


@router.get("/media/{kind}/{obj_id}")
def media(
    kind: str, obj_id: str, exp: int, sig: str, request: Request, db: Session = Depends(get_db)
) -> Response:
    if kind not in ("c", "p") or not verify(kind, obj_id, exp, sig):
        raise ApiError(403, "media_link_expired")
    if kind == "c":
        clip = db.get(Clip, obj_id)
        if clip is None or not clip.audio_key:
            raise ApiError(404, "not_found")
        space = db.get(Space, clip.space_id)
        key, ctype = clip.audio_key, "audio/mpeg"
    else:
        asset = db.get(Asset, obj_id)
        if asset is None or not asset.thumb_key:
            raise ApiError(404, "not_found")
        space = db.get(Space, asset.space_id)
        key, ctype = asset.thumb_key, "image/jpeg"
    if space is None:
        raise ApiError(404, "not_found")
    try:
        data = blobstore.load(space, key)
    except StorageNotFound as e:
        raise ApiError(404, "not_found") from e
    return _serve(data, ctype, request, exp)
