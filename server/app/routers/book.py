"""목소리가 들리는 기억책과 기억 통화 API."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Book, User
from app.routers.auth import client_ip
from app.routers.chat import _consent, _count_chat, _sample_rate_limit
from app.schemas import Book as BookOut
from app.schemas import BookParagraphUpdate, CallRequest, CallResponse, StoryRequest
from app.security.auth import SpaceAccess, space_editor, space_reader
from app.services import book as svc

router = APIRouter(tags=["book"])


def _can_edit(access: SpaceAccess) -> bool:
    return not access.space.is_sample and access.role in ("owner", "editor")


def _owner_consent(db: Session, access: SpaceAccess) -> bool:
    if access.space.is_sample:
        return False
    return _consent(db.get(User, access.space.owner_id))


def _get(db: Session, space_id: str) -> Book | None:
    return db.scalar(select(Book).where(Book.space_id == space_id))


@router.get("/spaces/{space_id}/book", response_model=BookOut)
def get_book(access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)) -> BookOut:
    book = _get(db, access.space.id)
    if book is None and access.space.is_sample and svc.source_clip_count(db, access.space.id):
        # 샘플(가상 인물) 공간은 처음 열 때 한 번 만들어 둔다
        try:
            book = svc.generate_book(db, access.space, consent=False)
            db.commit()
        except IntegrityError:
            db.rollback()
            book = _get(db, access.space.id)
    user_id = access.user.id if access.user else None
    return svc.book_out(db, access.space, book, user_id=user_id, can_edit=_can_edit(access))


@router.post("/spaces/{space_id}/book/generate", response_model=BookOut)
def generate(access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)) -> BookOut:
    if access.space.is_sample:
        raise ApiError(403, "sample_read_only")
    book = svc.generate_book(db, access.space, consent=_owner_consent(db, access))
    db.commit()
    db.refresh(book)
    return svc.book_out(db, access.space, book, user_id=access.user.id if access.user else None, can_edit=True)


@router.post("/spaces/{space_id}/book/stories", response_model=BookOut)
def add_story(
    body: StoryRequest,
    request: Request,
    access: SpaceAccess = Depends(space_reader),
    db: Session = Depends(get_db),
) -> BookOut:
    """가족이 적은 기억으로 이야기 한 장. 샘플 공간은 체험용으로 누구나(속도 제한) 더할 수 있다."""
    if access.space.is_sample:
        _sample_rate_limit(client_ip(request))
    else:
        access.require("editor")
    book = svc.add_story(db, access.space, body.prompt, consent=_owner_consent(db, access))
    db.commit()
    db.refresh(book)
    user_id = access.user.id if access.user else None
    return svc.book_out(db, access.space, book, user_id=user_id, can_edit=_can_edit(access))


@router.delete("/spaces/{space_id}/book/chapters/{chapter_id}", response_model=BookOut)
def delete_chapter(
    chapter_id: str, access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)
) -> BookOut:
    book = _get(db, access.space.id)
    if book is None or access.space.is_sample:
        raise ApiError(404, "not_found")
    svc.delete_chapter(book, chapter_id)
    db.commit()
    db.refresh(book)
    return svc.book_out(db, access.space, book, user_id=access.user.id if access.user else None, can_edit=True)


@router.patch("/spaces/{space_id}/book/paragraphs/{paragraph_id}", response_model=BookOut)
def edit_paragraph(
    paragraph_id: str,
    body: BookParagraphUpdate,
    access: SpaceAccess = Depends(space_editor),
    db: Session = Depends(get_db),
) -> BookOut:
    book = _get(db, access.space.id)
    if book is None or access.space.is_sample:
        raise ApiError(404, "not_found")
    svc.update_paragraph(db, book, paragraph_id, body.text)
    db.commit()
    db.refresh(book)
    return svc.book_out(db, access.space, book, user_id=access.user.id if access.user else None, can_edit=True)


@router.post("/spaces/{space_id}/book/approve", response_model=BookOut)
def approve(access: SpaceAccess = Depends(space_editor), db: Session = Depends(get_db)) -> BookOut:
    book = _get(db, access.space.id)
    if book is None or access.space.is_sample:
        raise ApiError(404, "not_found")
    book.status = "approved"
    book.approved_at = dt.datetime.now(dt.UTC)
    db.commit()
    db.refresh(book)
    return svc.book_out(db, access.space, book, user_id=access.user.id if access.user else None, can_edit=True)


@router.post("/spaces/{space_id}/book/chapters/{chapter_id}/call", response_model=CallResponse)
def memory_call(
    chapter_id: str,
    body: CallRequest,
    request: Request,
    access: SpaceAccess = Depends(space_reader),
    db: Session = Depends(get_db),
) -> CallResponse:
    book = _get(db, access.space.id)
    if book is None:
        raise ApiError(404, "not_found")
    remaining = None
    if access.user is None:
        _sample_rate_limit(client_ip(request))
    else:
        remaining = _count_chat(db, access.user)
        db.commit()
    resp = svc.call(
        db,
        access.space,
        book,
        chapter_id,
        body.message,
        body.history,
        user_id=access.user.id if access.user else None,
        consent=_owner_consent(db, access),
    )
    resp.remaining_today = remaining
    return resp
