"""처리 파이프라인: 정규화 → STT → 화자 분리 → 문장 단위 클립 → 태깅 → 색인.

단계마다 상태를 DB에 기록해 화면에서 진행 상황을 보여 준다. 로그에는 ID와 오류 코드만 남긴다.
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai import guard, registry
from app.ai.base import ProviderError
from app.ai.embedding import pack
from app.ai.speaker_split import split_by_content
from app.config import get_settings
from app.db import new_session
from app.models import Asset, Clip, Space, Speaker, User
from app.pipeline import media
from app.pipeline.dates import date_from_filename, date_from_metadata
from app.pipeline.segment import make_clips
from app.schemas import TranscriptSegment
from app.search.lexicon import rule_tags
from app.search.query import doc_tokens
from app.search.tokenizer import get_tokenizer
from app.storage import blobstore

log = logging.getLogger("yeoun.pipeline")

AUDIO_STAGES = ["normalize", "stt", "diarize", "segment", "tag", "index"]
PHOTO_STAGES = ["normalize"]

STAGE_ERRORS = {
    "unreadable_media": "파일을 읽을 수 없어요. 다른 형식으로 저장해 다시 올려 주세요.",
    "no_audio": "이 파일에는 소리가 없어요.",
    "too_long": "녹음이 너무 길어요. 나눠서 올려 주세요.",
    "normalize_failed": "소리를 꺼내지 못했어요. 파일이 손상되었을 수 있어요.",
    "stt_failed": "음성을 글로 바꾸는 중 문제가 생겼어요. 다시 시도해 주세요.",
    "clip_failed": "클립을 자르는 중 문제가 생겼어요. 다시 시도해 주세요.",
    "photo_failed": "사진을 열 수 없어요.",
    "ffmpeg_missing": "서버에 ffmpeg가 없어 처리할 수 없어요. 관리자에게 알려 주세요.",
    "internal": "처리 중 문제가 생겼어요. 다시 시도해 주세요.",
}


class StageFailed(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def initial_stages(asset: Asset) -> list[dict]:
    names = PHOTO_STAGES if asset.kind == "photo" else AUDIO_STAGES
    return [{"name": n, "state": "pending", "note": None} for n in names]


def _set_stage(db: Session, asset: Asset, name: str, state: str, note: str | None = None) -> None:
    stages = [dict(s) for s in (asset.stages or initial_stages(asset))]
    for s in stages:
        if s["name"] == name:
            s["state"] = state
            if note is not None:
                s["note"] = note
    asset.stages = stages
    done = sum(1 for s in stages if s["state"] in ("done", "skipped"))
    asset.progress = round(done / len(stages), 3)
    db.commit()


def _owner_consent(db: Session, space: Space) -> bool:
    owner = db.get(User, space.owner_id)
    return bool(owner and (owner.prefs or {}).get("consent_training_providers"))


def process_asset(asset_id: str) -> None:
    db = new_session()
    try:
        asset = db.get(Asset, asset_id)
        if asset is None:
            return
        space = db.get(Space, asset.space_id)
        assert space is not None
        asset.status = "processing"
        asset.error_code = None
        asset.error_message = None
        asset.stages = initial_stages(asset)
        asset.progress = 0.0
        db.commit()
        try:
            if asset.kind == "photo":
                _process_photo(db, asset, space)
            else:
                _process_audio(db, asset, space)
            asset.status = "ready"
            asset.progress = 1.0
            db.commit()
            log.info("asset_ready asset=%s", asset.id)
        except StageFailed as e:
            db.rollback()
            _fail(db, asset_id, e.code)
            raise
        except media.MediaError as e:
            db.rollback()
            _fail(db, asset_id, e.code if e.code in STAGE_ERRORS else "internal")
            raise StageFailed(e.code) from e
        except Exception:
            db.rollback()
            log.exception("pipeline_crash asset=%s", asset_id)
            _fail(db, asset_id, "internal")
            raise
    finally:
        db.close()


def _fail(db: Session, asset_id: str, code: str) -> None:
    asset = db.get(Asset, asset_id)
    if asset is None:
        return
    stages = [dict(s) for s in (asset.stages or initial_stages(asset))]
    for s in stages:
        if s["state"] == "running":
            s["state"] = "failed"
    asset.stages = stages
    asset.status = "failed"
    asset.error_code = code
    asset.error_message = STAGE_ERRORS.get(code, STAGE_ERRORS["internal"])
    db.commit()
    log.info("asset_failed asset=%s code=%s", asset_id, code)


# ---------------------------------------------------------------- 사진


def _process_photo(db: Session, asset: Asset, space: Space) -> None:
    from PIL import Image, ImageOps

    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:  # noqa: S110 - HEIC를 못 열면 아래에서 photo_failed
        pass
    Image.MAX_IMAGE_PIXELS = get_settings().max_photo_pixels
    _set_stage(db, asset, "normalize", "running")
    raw = blobstore.load(space, asset.storage_key or "")
    try:
        img = Image.open(io.BytesIO(raw))
        exif = img.getexif()
        taken = None
        try:
            sub = exif.get_ifd(0x8769)
            taken = sub.get(36867) or sub.get(36868)
        except Exception:
            taken = None
        taken = taken or exif.get(306)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
    except Exception as e:
        raise StageFailed("photo_failed") from e
    if asset.date_source in ("upload", "unknown"):
        d = date_from_metadata(str(taken).replace(":", "-", 2) if taken else None)
        if d:
            asset.recorded_at = d
            asset.date_source = "exif"
    key = blobstore.asset_prefix(space.id, asset.id) + "thumb.jpg"
    blobstore.save(db, space, key, buf.getvalue(), asset_id=asset.id)
    asset.thumb_key = key
    _set_stage(db, asset, "normalize", "done")


# ---------------------------------------------------------------- 음성·영상


def _process_audio(db: Session, asset: Asset, space: Space) -> None:
    s = get_settings()
    consent = _owner_consent(db, space)
    is_sample = space.is_sample
    with tempfile.TemporaryDirectory(prefix="yeoun-proc-") as tmpdir:
        tmp = Path(tmpdir)
        src = tmp / f"original.{asset.ext}"
        src.write_bytes(blobstore.load(space, asset.storage_key or ""))
        wav = tmp / "audio.wav"

        # 1) 정규화
        _set_stage(db, asset, "normalize", "running")
        info = media.probe(src)
        if not info.has_audio:
            raise StageFailed("no_audio")
        if info.duration > s.max_audio_minutes * 60:
            raise StageFailed("too_long")
        media.to_wav16k(src, wav)
        duration = media.probe(wav).duration or info.duration
        asset.duration_sec = round(duration, 2)
        if asset.date_source in ("upload", "unknown"):
            d = date_from_metadata(info.creation_time)
            if d:
                asset.recorded_at = d
                asset.date_source = "metadata"
        _set_stage(db, asset, "normalize", "done")

        # 2) 음성 인식
        _set_stage(db, asset, "stt", "running")
        stt, res = registry.build("stt", consent=consent, is_sample=is_sample)
        try:
            segments = stt.transcribe(wav, sha256=asset.sha256, duration=duration)
        except ProviderError as e:
            log.warning("stt_failed asset=%s provider=%s code=%s", asset.id, stt.name, e.code)
            raise StageFailed("stt_failed") from e
        note = res.note
        if stt.name == "mock" and segments and not any(x.text for x in segments):
            note = "음성 인식이 꺼져 있어 말소리 구간만 나눴어요. 목소리 확인에서 자막을 적을 수 있어요."
        _set_stage(db, asset, "stt", "done", note)

        # 3) 화자 분리
        if asset.source == "ahead":
            segments = [x.model_copy(update={"speaker": "S1"}) for x in segments]
            diarized = True
            _set_stage(db, asset, "diarize", "skipped", "미리 남기기 녹음은 그 사람 목소리로 바로 표시해요.")
        else:
            _set_stage(db, asset, "diarize", "running")
            diar, dres = registry.build("diarization", consent=consent, is_sample=is_sample)
            try:
                segments, diarized = diar.diarize(wav, segments, duration)
            except ProviderError as e:
                log.warning("diarize_failed asset=%s code=%s", asset.id, e.code)
                segments, diarized = [x.model_copy(update={"speaker": None}) for x in segments], False
            dnote = None if diarized else "화자를 나누지 않았어요. 목소리 확인에서 직접 골라 주세요."
            # 통화·영상인데 목소리가 하나로만 나왔으면(비슷한 목소리·한쪽만 녹음·합성 음성) 내용으로 나눈다
            voices = {x.speaker for x in segments if x.text.strip()}
            if asset.origin in ("call", "video", "other") and len(voices) <= 1:
                llm, _ = registry.build("llm", consent=consent, is_sample=is_sample)
                split, ok = split_by_content(segments, llm)
                if ok:
                    segments, diarized = split, True
                    dnote = "목소리로는 나뉘지 않아 말한 내용으로 두 사람을 나눴어요. 목소리 확인에서 꼭 들어 보고 골라 주세요."
            _set_stage(db, asset, "diarize", "done" if diarized else "skipped", dnote)
        asset.diarized = diarized

        # 4) 문장 단위 클립
        _set_stage(db, asset, "segment", "running")
        _replace_clips(db, asset, space, wav, segments, duration)
        _set_stage(db, asset, "segment", "done")

        # 5) 태깅
        _set_stage(db, asset, "tag", "running")
        tnote = _tag_clips(db, asset, consent, is_sample)
        _set_stage(db, asset, "tag", "done", tnote)

        # 6) 색인
        _set_stage(db, asset, "index", "running")
        inote = index_clips(db, space, asset_id=asset.id, consent=consent)
        space.index_version += 1
        _set_stage(db, asset, "index", "done", inote)


def _speaker_label(i: int) -> str:
    return f"목소리 {i + 1}"


def _replace_clips(
    db: Session, asset: Asset, space: Space, wav: Path, segments: list[TranscriptSegment], duration: float
) -> None:
    # 다시 처리하는 경우 예전 클립·화자·파일을 지운다 (원본은 남긴다)
    old_keys = db.scalars(
        select(Clip.audio_key).where(Clip.asset_id == asset.id, Clip.audio_key.is_not(None))
    ).all()
    for k in old_keys:
        if k:
            blobstore.remove(db, k)
    db.execute(delete(Clip).where(Clip.asset_id == asset.id))
    db.execute(delete(Speaker).where(Speaker.asset_id == asset.id))
    db.flush()

    spans = make_clips(segments, duration)
    speakers: dict[str | None, Speaker] = {}
    order: list[str | None] = []
    for sp in spans:
        if sp.speaker not in speakers:
            order.append(sp.speaker)
            if asset.source == "ahead":
                label, role = "녹음하신 분", "person"
            elif sp.speaker is None:
                label, role = "이 파일의 목소리", "unknown"
            else:
                label, role = _speaker_label(len(order) - 1), "unknown"
            spk = Speaker(asset_id=asset.id, space_id=space.id, label=label, role=role)
            db.add(spk)
            speakers[sp.speaker] = spk
    db.flush()

    with tempfile.TemporaryDirectory(prefix="yeoun-clip-") as tmpdir:
        for i, sp in enumerate(spans):
            clip = Clip(
                asset_id=asset.id,
                space_id=space.id,
                speaker_id=speakers[sp.speaker].id,
                seq=i,
                start_sec=sp.start,
                end_sec=sp.end,
                text=sp.text,
                text_original=sp.text,
                confidence=sp.confidence,
                audio_status="missing",
            )
            db.add(clip)
            db.flush()
            out = Path(tmpdir) / f"{clip.id}.mp3"
            media.cut_clip(wav, sp.start, sp.end, out)
            key = blobstore.asset_prefix(space.id, asset.id) + f"clips/{clip.id}.mp3"
            blobstore.save(db, space, key, out.read_bytes(), asset_id=asset.id)
            out.unlink(missing_ok=True)
            clip.audio_key = key
            clip.audio_status = "ready"
    db.commit()


def _tag_clips(db: Session, asset: Asset, consent: bool, is_sample: bool) -> str | None:
    clips = db.scalars(select(Clip).where(Clip.asset_id == asset.id).order_by(Clip.seq)).all()
    items = [(c.id, c.text) for c in clips if c.text.strip()]
    tagged: dict[str, list[str]] = {}
    note = None
    if items:
        llm, res = registry.build("llm", consent=consent, is_sample=is_sample)
        for i in range(0, len(items), 30):
            batch = items[i : i + 30]
            try:
                raw = llm.tag(batch)
                tagged.update(guard.validate_tagging(raw, [cid for cid, _ in batch]))
            except ProviderError as e:
                log.warning("tagging_fallback asset=%s code=%s", asset.id, e.code)
                note = "AI 태깅에 실패해 규칙으로 태그를 붙였어요."
    question_tags: list[str] = []
    if asset.question_text:
        # 질문 카드에 붙은 태그 + 질문 문장 분석 (질문과 연결된 답은 이 태그로도 찾는다)
        from app.routers.ahead import deck
        from app.search.lexicon import analyze

        card = next((c for c in deck().cards if c.id == asset.question_id), None)
        question_tags = list(dict.fromkeys(list(card.tags or []) if card else []))
        question_tags += [t for t in analyze(asset.question_text).tags if t not in question_tags]
    for c in clips:
        tags = tagged.get(c.id)
        if tags is None:
            tags = rule_tags(c.text) if c.text.strip() else []
        merged = list(dict.fromkeys(tags + question_tags))[:6]
        c.tags = merged
    db.commit()
    return note


def index_clips(
    db: Session,
    space: Space,
    *,
    asset_id: str | None = None,
    clip_ids: list[str] | None = None,
    consent: bool = False,
) -> str | None:
    """클립의 검색 토큰(과 가능하면 임베딩)을 다시 만든다."""
    q = (
        select(Clip, Asset.question_text)
        .join(Asset, Asset.id == Clip.asset_id)
        .where(Clip.space_id == space.id)
    )
    if asset_id:
        q = q.where(Clip.asset_id == asset_id)
    if clip_ids is not None:
        q = q.where(Clip.id.in_(clip_ids))
    rows = db.execute(q).all()
    tok_name = get_tokenizer().name
    for clip, question in rows:
        clip.tokens = doc_tokens(clip.text, clip.tags or [], question)
        clip.tokenizer = tok_name
    note = None
    texts = [(clip, clip.text) for clip, _ in rows if clip.text.strip()]
    if texts:
        embedder, res = registry.build("embedding", consent=consent, is_sample=space.is_sample)
        if embedder.live:
            try:
                vecs = embedder.embed([t for _, t in texts]) or []
                for (clip, _), v in zip(texts, vecs, strict=False):
                    clip.embedding = pack(v)
                    clip.embedding_model = f"{embedder.name}:{embedder.model}"
            except ProviderError as e:
                log.warning("embedding_skipped space=%s code=%s", space.id, e.code)
                note = "임베딩을 만들지 못해 낱말 검색만 써요."
    db.commit()
    return note


__all__ = ["process_asset", "index_clips", "initial_stages", "date_from_filename"]
