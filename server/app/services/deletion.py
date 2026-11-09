"""완전 삭제: 파일, 자막, 색인, 작업 기록까지 지운다."""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Asset, Job, Space
from app.search.index import drop_space_index
from app.storage import blobstore

log = logging.getLogger("yeoun.deletion")


def delete_asset_completely(db: Session, asset: Asset) -> None:
    space_id = asset.space_id
    n = blobstore.remove_asset_files(db, space_id, asset.id)
    db.execute(delete(Job).where(Job.asset_id == asset.id))
    db.delete(asset)  # clips·speakers·stored_objects는 FK CASCADE
    space = db.get(Space, space_id)
    if space is not None:
        space.index_version += 1
    db.flush()
    drop_space_index(space_id)
    log.info("asset_deleted asset=%s files=%d", asset.id, n)


def delete_space_completely(db: Session, space: Space) -> None:
    space_id = space.id
    n = blobstore.remove_space_files(db, space_id)
    db.delete(space)  # members·assets·clips·speakers·jobs·links·collections는 FK CASCADE
    db.flush()
    drop_space_index(space_id)
    log.info("space_deleted space=%s files=%d", space_id, n)
