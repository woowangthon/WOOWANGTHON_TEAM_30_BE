"""설정: 외부 서비스·보관 기간 안내, 전체 내보내기."""

from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import registry
from app.config import get_settings
from app.db import get_db
from app.models import Asset, Clip, Speaker, User
from app.schemas import ProviderInfo, ProviderList
from app.security.auth import SpaceAccess, space_owner, space_reader
from app.storage import StorageNotFound, blobstore

router = APIRouter(tags=["settings"])

RETENTION = [
    "원본 파일·클립·사진은 공간별 키로 암호화해 보관하고, 자료나 공간을 지우면 바로 지워요.",
    "자막·태그·검색 색인·처리 기록은 자료와 함께 지워져요.",
    "대화 내용은 서버에 저장하지 않아요. 이 브라우저 탭에만 잠시 남아요(하루 대화 횟수만 셉니다).",
    "음성으로 말 걸기 녹음은 글자로 바꾼 뒤 바로 지워요.",
    "계정을 지우면 내가 만든 공간과 그 안의 모든 자료가 함께 지워져요.",
    "서버 로그에는 자막·파일명을 남기지 않아요(요청 경로와 오류 코드만).",
]


@router.get("/spaces/{space_id}/providers", response_model=ProviderList)
def providers(access: SpaceAccess = Depends(space_reader), db: Session = Depends(get_db)) -> ProviderList:
    owner = db.get(User, access.space.owner_id)
    consent = bool(owner and (owner.prefs or {}).get("consent_training_providers"))
    rows = registry.describe_all(consent=consent)
    infos = [
        ProviderInfo(
            function=r["meta"].function,
            provider=r["meta"].name,
            display_name=r["meta"].display_name,
            is_external=r["meta"].is_external,
            trains_on_input=r["meta"].trains_on_input,
            data_sent=r["meta"].data_sent,
            retention_note=r["meta"].retention_note,
            status=r["status"],
            note=r["note"],
        )
        for r in rows
    ]
    storage_note = {
        "local": "파일은 여운 서버의 디스크에 암호화해 보관해요.",
        "db": "파일은 여운 데이터베이스에 암호화해 보관해요(시연용, 용량 제한).",
        "s3": "파일은 S3 호환 저장소(예: Cloudflare R2)에 암호화해 보관해요. 저장소 업체는 내용을 볼 수 없어요.",
    }[get_settings().storage]
    return ProviderList(providers=infos, retention=[storage_note, *RETENTION])


_UNSAFE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")


def _safe_name(name: str) -> str:
    return _UNSAFE.sub("_", name).strip(" .")[:120] or "file"


@router.get("/spaces/{space_id}/export")
def export_space(
    access: SpaceAccess = Depends(space_owner), db: Session = Depends(get_db)
) -> StreamingResponse:
    """전체 내보내기: 원본 파일 + 자막·클립 정보 JSON (zip)."""
    space = access.space
    assets = db.scalars(select(Asset).where(Asset.space_id == space.id).order_by(Asset.created_at)).all()
    clips = db.execute(
        select(Clip, Speaker.label, Speaker.role)
        .outerjoin(Speaker, Speaker.id == Clip.speaker_id)
        .where(Clip.space_id == space.id)
        .order_by(Clip.asset_id, Clip.seq)
    ).all()
    tmp = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)  # noqa: SIM115 - 응답이 끝날 때 닫힌다
    used: set[str] = set()
    manifest_assets = []
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for a in assets:
            prefix = a.recorded_at.isoformat() if a.recorded_at else "날짜모름"
            name = f"원본/{prefix}_{_safe_name(a.filename)}"
            while name in used:
                name = name.replace("원본/", "원본/_", 1)
            used.add(name)
            try:
                z.writestr(name, blobstore.load(space, a.storage_key or ""), compress_type=zipfile.ZIP_STORED)
                file_ok = True
            except (StorageNotFound, ValueError):
                file_ok = False
            manifest_assets.append(
                {
                    "id": a.id,
                    "file": name if file_ok else None,
                    "filename": a.filename,
                    "kind": a.kind,
                    "origin": a.origin,
                    "recorded_at": a.recorded_at.isoformat() if a.recorded_at else None,
                    "duration_sec": a.duration_sec,
                    "question": a.question_text,
                    "caption": a.caption,
                }
            )
        transcripts = {
            "space": {
                "name": space.name,
                "person_name": space.person_name,
                "relationship": space.relationship,
                "birthday": space.birthday.isoformat() if space.birthday else None,
                "memorial_day": space.memorial_day.isoformat() if space.memorial_day else None,
            },
            "exported_at": dt.datetime.now(dt.UTC).isoformat(),
            "assets": manifest_assets,
            "clips": [
                {
                    "id": c.id,
                    "asset_id": c.asset_id,
                    "start_sec": c.start_sec,
                    "end_sec": c.end_sec,
                    "text": c.text,
                    "text_original": c.text_original,
                    "text_edited": c.text_edited,
                    "tags": c.tags,
                    "speaker": label,
                    "speaker_role": role,
                    "include_override": c.include_override,
                }
                for c, label, role in clips
            ],
        }
        z.writestr("자막.json", json.dumps(transcripts, ensure_ascii=False, indent=2))
        z.writestr(
            "읽어 주세요.txt",
            "여운에서 내보낸 자료예요.\n\n"
            "- 원본/ : 올린 파일 원본(암호를 푼 상태). 이 zip을 안전한 곳에 보관해 주세요.\n"
            "- 자막.json : 녹음별 자막, 클립 구간(초), 태그, 목소리 구분.\n"
            "  클립은 원본 파일의 start_sec~end_sec 구간이에요.\n",
        )
    tmp.seek(0)
    filename = f"여운-{_safe_name(space.name)}-{dt.date.today():%Y%m%d}.zip"

    def stream():
        try:
            while chunk := tmp.read(1024 * 1024):
                yield chunk
        finally:
            tmp.close()

    return StreamingResponse(
        stream(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"yeoun-export.zip\"; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )
