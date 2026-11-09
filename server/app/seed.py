"""샘플 공간 만들기: `make seed` / `python -m app.seed`

가상 인물 "[샘플] 김순자 할머니"의 클립 40개(자막 fixture)와 사진 placeholder를 넣는다.
- 실제 녹음은 아직 없으니 오디오는 placeholder('샘플 녹음 준비 중')로 둔다.
- 팀원이 docs/demo-recording-script.md 대본을 녹음해 fixtures/demo/demo-01.m4a … 를 넣으면
  그 파일을 원본 클립으로 쓴다(placeholder 대신).
- fixture와 녹음 파일이 바뀌지 않았으면 다시 만들지 않는다(서버 시작 때마다 불러도 빠르다).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import logging
import secrets
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import FIXTURES_DIR
from app.db import session_scope
from app.models import Asset, Clip, Space, Speaker, User
from app.pipeline import media
from app.schemas import SpaceCreate
from app.search.query import doc_tokens
from app.search.tokenizer import get_tokenizer
from app.security.auth import hash_password
from app.services.deletion import delete_space_completely
from app.services.spaces import create_space
from app.storage import blobstore

log = logging.getLogger("yeoun.seed")

DEMO_DIR = FIXTURES_DIR / "demo"
SAMPLE_JSON = DEMO_DIR / "sample-space.json"
SYSTEM_EMAIL = "sample@yeoun.invalid"
AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".webm")
KST = dt.timezone(dt.timedelta(hours=9))
ORIGIN_NAMES = {"call": "통화 녹음", "video": "동영상", "voice_message": "음성 메시지", "ahead": "미리 남기기"}


def _audio_for(ref: str) -> Path | None:
    for ext in AUDIO_EXTS:
        p = DEMO_DIR / f"{ref}{ext}"
        if p.exists():
            return p
    return None


def fingerprint() -> str:
    h = hashlib.sha256(SAMPLE_JSON.read_bytes())
    for p in sorted(DEMO_DIR.glob("demo-*")):
        if p.suffix in AUDIO_EXTS:
            h.update(p.name.encode())
            h.update(str(p.stat().st_size).encode())
    h.update(get_tokenizer().name.encode())
    h.update(dt.datetime.now(KST).date().isoformat()[:7].encode())  # '@one_year_ago'가 달마다 맞게
    return h.hexdigest()[:20]


def one_year_ago_date(memorial: dt.date | None, today: dt.date) -> dt.date:
    """오늘과 같은 월·일 중 가장 최근 과거 날짜 (기일 이전)."""
    year = today.year - 1
    while True:
        try:
            d = today.replace(year=year)
        except ValueError:
            d = dt.date(year, 2, 28)
        if memorial is None or d <= memorial:
            return d
        year -= 1


def placeholder_photo(palette: list[str], seed: str) -> bytes:
    """가상 사진 자리: 부드러운 색 그라데이션과 단순한 도형 (실제 사진 아님)."""
    from PIL import Image, ImageDraw

    def hex_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    a, b = (hex_rgb(palette[0]), hex_rgb(palette[-1])) if palette else ((232, 213, 185), (180, 118, 90))
    w, h = 960, 720
    img = Image.new("RGB", (w, h), a)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        draw.line([(0, y), (w, y)], fill=tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3)))
    rnd = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    cx, cy, r = 200 + rnd % 560, 160 + (rnd >> 8) % 200, 70 + (rnd >> 16) % 60
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 250, 240))
    for i in range(3):
        x0 = (rnd >> (i * 5)) % w
        draw.ellipse([x0 - 260, h - 180 - i * 40, x0 + 260, h + 200], fill=tuple(max(0, c - 25 - i * 10) for c in b))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _system_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == SYSTEM_EMAIL))
    if user is None:
        user = User(
            email=SYSTEM_EMAIL,
            password_hash=hash_password(secrets.token_urlsafe(32)),  # 아무도 로그인할 수 없다
            display_name="여운 샘플",
            is_system=True,
            prefs={},
        )
        db.add(user)
        db.flush()
    return user


def seed_sample(force: bool = False) -> str:
    data = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    fp = fingerprint()
    with session_scope() as db:
        user = _system_user(db)
        existing = db.scalars(select(Space).where(Space.is_sample.is_(True))).all()
        if existing and not force and (user.prefs or {}).get("sample_fingerprint") == fp:
            log.info("sample up to date")
            return existing[0].id
        for s in existing:
            delete_space_completely(db, s)
        db.flush()

        info = data["space"]
        space = create_space(
            db,
            user,
            SpaceCreate(
                name=info["name"],
                person_name=info["person_name"],
                relationship=info.get("relationship"),
                birthday=info.get("birthday"),
                memorial_day=info.get("memorial_day"),
                note=info.get("note"),
            ),
            is_sample=True,
        )
        today = dt.datetime.now(KST).date()
        memorial = space.memorial_day
        questions = {}
        try:
            from app.routers.ahead import deck

            questions = {c.id: c.text for c in deck().cards}
        except Exception:  # noqa: S110 - 질문 카드가 없어도 샘플은 만든다
            pass

        with_audio = 0
        with tempfile.TemporaryDirectory(prefix="yeoun-seed-") as tmp:
            for item in data["clips"]:
                ref = item["ref"]
                date = one_year_ago_date(memorial, today) if item["date"] == "@one_year_ago" else dt.date.fromisoformat(item["date"])
                origin = item.get("source", "call")
                qid = item.get("question_id")
                asset = Asset(
                    space_id=space.id,
                    kind="video" if origin == "video" else "audio",
                    source="sample",
                    origin=origin if origin in ORIGIN_NAMES else "other",
                    filename=f"[샘플] {ORIGIN_NAMES.get(origin, '녹음')} {date.isoformat()} ({ref})",
                    ext="m4a",
                    size_bytes=0,
                    sha256=hashlib.sha256(ref.encode()).hexdigest(),
                    recorded_at=date,
                    date_source="metadata",
                    status="ready",
                    stages=[{"name": n, "state": "done", "note": None} for n in ("normalize", "stt", "diarize", "segment", "tag", "index")],
                    progress=1.0,
                    diarized=True,
                    voice_reviewed=True,
                    question_id=qid,
                    question_text=questions.get(qid) if qid else None,
                    sample_ref=ref,
                )
                db.add(asset)
                db.flush()
                speaker = Speaker(asset_id=asset.id, space_id=space.id, label=info["person_name"], role="person")
                db.add(speaker)
                db.flush()
                text = item["text"]
                duration = min(30.0, max(2.0, round(len(text) / 6.5, 1)))
                clip = Clip(
                    asset_id=asset.id,
                    space_id=space.id,
                    speaker_id=speaker.id,
                    seq=0,
                    start_sec=0.0,
                    end_sec=duration,
                    text=text,
                    text_original=text,
                    tags=item.get("tags", []),
                    audio_status="placeholder",
                    ref=ref,
                )
                db.add(clip)
                db.flush()
                audio = _audio_for(ref)
                if audio is not None:
                    out = Path(tmp) / f"{ref}.mp3"
                    try:
                        media.transcode_audio_for_playback(audio, out)
                        info_probe = media.probe(out)
                        key = blobstore.asset_prefix(space.id, asset.id) + f"clips/{clip.id}.mp3"
                        size = blobstore.save(db, space, key, out.read_bytes(), asset_id=asset.id)
                        clip.audio_key = key
                        clip.audio_status = "ready"
                        clip.end_sec = round(info_probe.duration or duration, 2)
                        asset.duration_sec = clip.end_sec
                        asset.size_bytes = size
                        with_audio += 1
                    except media.MediaError as e:
                        log.warning("sample audio skipped ref=%s code=%s", ref, e.code)
                clip.tokens = doc_tokens(text, clip.tags, asset.question_text)
                clip.tokenizer = get_tokenizer().name

            for p in data.get("photos", []):
                date = dt.date.fromisoformat(p["date"])
                asset = Asset(
                    space_id=space.id,
                    kind="photo",
                    source="sample",
                    origin="other",
                    filename=f"[샘플] 사진 {date.isoformat()} ({p['ref']})",
                    ext="jpg",
                    size_bytes=0,
                    sha256=hashlib.sha256(p["ref"].encode()).hexdigest(),
                    recorded_at=date,
                    date_source="exif",
                    status="ready",
                    stages=[{"name": "normalize", "state": "done", "note": None}],
                    progress=1.0,
                    caption=p.get("caption"),
                    sample_ref=p["ref"],
                    voice_reviewed=True,
                )
                db.add(asset)
                db.flush()
                key = blobstore.asset_prefix(space.id, asset.id) + "thumb.jpg"
                asset.size_bytes = blobstore.save(
                    db, space, key, placeholder_photo(p.get("palette", []), p["ref"]), asset_id=asset.id
                )
                asset.thumb_key = key
        space.index_version += 1
        prefs = dict(user.prefs or {})
        prefs["sample_fingerprint"] = fp
        user.prefs = prefs
        log.info("sample seeded clips=%d with_audio=%d photos=%d", len(data["clips"]), with_audio, len(data.get("photos", [])))
        print(f"샘플 공간을 만들었어요: 클립 {len(data['clips'])}개 (녹음 {with_audio}개), 사진 {len(data.get('photos', []))}장")
        return space.id


def main() -> None:
    from app.logging_setup import setup_logging

    setup_logging()
    parser = argparse.ArgumentParser(description="샘플 공간 만들기")
    parser.add_argument("--force", action="store_true", help="바뀐 것이 없어도 다시 만든다")
    args = parser.parse_args()
    seed_sample(force=args.force)


if __name__ == "__main__":
    main()


__all__ = ["seed_sample", "one_year_ago_date", "placeholder_photo"]
