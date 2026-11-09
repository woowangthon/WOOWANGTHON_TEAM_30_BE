from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Member, Space, User
from app.schemas import DeleteSpaceRequest, SpaceCreate, SpaceUpdate
from app.schemas import Space as SpaceOut
from app.security.auth import SpaceAccess, current_user, space_editor, space_owner, space_reader
from app.services.deletion import delete_space_completely
from app.services.spaces import create_space, space_out

router = APIRouter(tags=["spaces"])

MAX_SPACES_PER_USER = 20


@router.get("/spaces", response_model=list[SpaceOut])
def list_spaces(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[SpaceOut]:
    rows = db.execute(
        select(Space, Member.role)
        .join(Member, Member.space_id == Space.id)
        .where(Member.user_id == user.id)
        .order_by(Space.created_at)
    ).all()
    return [space_out(db, space, role) for space, role in rows]


@router.post("/spaces", response_model=SpaceOut, status_code=201)
def create(body: SpaceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> SpaceOut:
    owned = db.scalars(select(Space.id).where(Space.owner_id == user.id)).all()
    if len(owned) >= MAX_SPACES_PER_USER:
        raise ApiError(400, "bad_request", "공간은 한 사람당 20개까지 만들 수 있어요.")
    space = create_space(db, user, body)
    db.commit()
    return space_out(db, space, "owner")


@router.get("/spaces/{space_id}", response_model=SpaceOut)
def get_space(access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)) -> SpaceOut:
    return space_out(db, access.space, access.role)


@router.patch("/spaces/{space_id}", response_model=SpaceOut)
def update_space(
    body: SpaceUpdate, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> SpaceOut:
    space = access.space
    data = body.model_dump(exclude_unset=True)
    for key in ("name", "person_name"):
        if key in data and data[key]:
            setattr(space, key, data[key].strip())
    for key in ("relationship", "birthday", "memorial_day", "note"):
        if key in data:
            setattr(space, key, data[key])
    db.commit()
    return space_out(db, space, access.role)


@router.post("/spaces/{space_id}/delete", status_code=204)
def delete_space(
    body: DeleteSpaceRequest, access: SpaceAccess = Depends(space_owner), db: Session = Depends(get_db)
) -> Response:
    """공간 완전 삭제 (파일·자막·색인·작업 기록·초대·녹음 링크 모두)."""
    if body.confirm_name.strip() != access.space.name:
        raise ApiError(400, "confirm_mismatch")
    delete_space_completely(db, access.space)
    db.commit()
    return Response(status_code=204)
