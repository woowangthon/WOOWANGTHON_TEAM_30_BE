"""클립 모음 (P1): 예) '엄마의 잔소리 모음'. 그 사람 목소리로 확인된 클립만 담는다."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Clip, Collection, Speaker
from app.schemas import Collection as CollectionOut
from app.schemas import CollectionCreate, CollectionList, CollectionUpdate
from app.security.auth import SpaceAccess, space_editor, space_reader
from app.services.assets import clip_cards
from app.services.spaces import included_expr

router = APIRouter(tags=["collections"])


def _valid_clip_ids(db: Session, space_id: str, ids: list[str]) -> list[str]:
    if not ids:
        return []
    ok = set(
        db.scalars(
            select(Clip.id)
            .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
            .where(Clip.space_id == space_id, Clip.id.in_(ids), included_expr())
        )
    )
    return [i for i in dict.fromkeys(ids) if i in ok]


def _out(db: Session, c: Collection, user_id: str | None, with_clips: bool) -> CollectionOut:
    ids = _valid_clip_ids(db, c.space_id, c.clip_ids or [])
    return CollectionOut(
        id=c.id,
        title=c.title,
        clip_ids=ids,
        clips=clip_cards(db, c.space_id, ids, user_id) if with_clips else [],
        created_at=c.created_at,
    )


@router.get("/spaces/{space_id}/collections", response_model=CollectionList)
def list_collections(
    access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)
) -> CollectionList:
    rows = db.scalars(
        select(Collection)
        .where(Collection.space_id == access.space.id)
        .order_by(Collection.created_at.desc())
    ).all()
    return CollectionList(collections=[_out(db, c, None, False) for c in rows])


@router.post("/spaces/{space_id}/collections", response_model=CollectionOut, status_code=201)
def create_collection(
    body: CollectionCreate, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> CollectionOut:
    c = Collection(
        space_id=access.space.id,
        title=body.title.strip(),
        clip_ids=_valid_clip_ids(db, access.space.id, body.clip_ids or []),
        created_by=access.user.id if access.user else None,
    )
    db.add(c)
    db.commit()
    return _out(db, c, access.user.id if access.user else None, True)


def _get(db: Session, space_id: str, cid: str) -> Collection:
    c = db.get(Collection, cid)
    if c is None or c.space_id != space_id:
        raise ApiError(404, "not_found")
    return c


@router.get("/spaces/{space_id}/collections/{collection_id}", response_model=CollectionOut)
def get_collection(
    collection_id: str, access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)
) -> CollectionOut:
    return _out(db, _get(db, access.space.id, collection_id), access.user.id if access.user else None, True)


@router.patch("/spaces/{space_id}/collections/{collection_id}", response_model=CollectionOut)
def update_collection(
    collection_id: str,
    body: CollectionUpdate,
    access: SpaceAccess = Depends(space_editor),
    db: Session = Depends(get_db),
) -> CollectionOut:
    c = _get(db, access.space.id, collection_id)
    if body.title:
        c.title = body.title.strip()
    if body.clip_ids is not None:
        c.clip_ids = _valid_clip_ids(db, access.space.id, body.clip_ids)
    db.commit()
    return _out(db, c, access.user.id if access.user else None, True)


@router.delete("/spaces/{space_id}/collections/{collection_id}", status_code=204)
def delete_collection(
    collection_id: str, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> Response:
    db.delete(_get(db, access.space.id, collection_id))
    db.commit()
    return Response(status_code=204)
