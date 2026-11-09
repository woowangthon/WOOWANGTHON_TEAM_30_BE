"""작업 처리기.

- 별도 프로세스: `python -m app.worker`
- YEOUN_WORKER_INLINE=true: API 프로세스 안의 스레드 (Render 무료 등급은 백그라운드 워커가 없다)

작업은 PostgreSQL `FOR UPDATE SKIP LOCKED`로 하나씩 가져간다. 서버가 잠들거나 재시작되어
'running'으로 남은 작업은 잠금 시간이 지나면 다시 가져간다(최대 3번).
"""

from __future__ import annotations

import datetime as dt
import logging
import threading

from sqlalchemy import or_, select

from app.db import new_session
from app.models import Asset, Job, utcnow

log = logging.getLogger("yeoun.worker")

LOCK_MINUTES = 20
MAX_ATTEMPTS = 3


def enqueue(db, asset: Asset) -> Job:
    from app.pipeline.process import initial_stages

    job = Job(space_id=asset.space_id, asset_id=asset.id, kind="process_asset", status="queued")
    db.add(job)
    asset.status = "queued"
    asset.stages = initial_stages(asset)
    asset.progress = 0.0
    asset.error_code = None
    asset.error_message = None
    return job


def claim_next() -> tuple[str, str] | None:
    db = new_session()
    try:
        now = utcnow()
        job = db.scalar(
            select(Job)
            .where(
                or_(
                    Job.status == "queued",
                    (Job.status == "running") & (Job.locked_until < now) & (Job.attempts < MAX_ATTEMPTS),
                )
            )
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_until = now + dt.timedelta(minutes=LOCK_MINUTES)
        db.commit()
        return job.id, job.asset_id
    finally:
        db.close()


def _finish(job_id: str, status: str, error_code: str | None = None) -> None:
    db = new_session()
    try:
        job = db.get(Job, job_id)
        if job is not None:
            job.status = status
            job.error_code = error_code
            job.locked_until = None
            db.commit()
    finally:
        db.close()


def run_one() -> bool:
    """작업 하나를 처리했으면 True."""
    from app.pipeline.process import StageFailed, process_asset

    claimed = claim_next()
    if claimed is None:
        return False
    job_id, asset_id = claimed
    try:
        process_asset(asset_id)
        _finish(job_id, "done")
    except StageFailed as e:
        _finish(job_id, "failed", e.code)
    except Exception:
        log.exception("job_crash job=%s", job_id)
        _finish(job_id, "failed", "internal")
    return True


def run_pending_jobs(limit: int = 100) -> int:
    n = 0
    while n < limit and run_one():
        n += 1
    return n


def reset_stuck_jobs() -> None:
    """시작할 때: 잠금이 지난 running 작업이 MAX_ATTEMPTS를 넘었으면 실패로 정리."""
    db = new_session()
    try:
        now = utcnow()
        stuck = db.scalars(
            select(Job).where(Job.status == "running", Job.locked_until < now, Job.attempts >= MAX_ATTEMPTS)
        ).all()
        for job in stuck:
            job.status = "failed"
            job.error_code = "internal"
            asset = db.get(Asset, job.asset_id)
            if asset and asset.status in ("queued", "processing"):
                asset.status = "failed"
                asset.error_code = "internal"
                asset.error_message = "처리 중 서버가 다시 시작됐어요. 다시 시도해 주세요."
        db.commit()
    finally:
        db.close()


class InlineWorker:
    def __init__(self, poll: float | None = None):
        from app.config import get_settings

        self.poll = poll if poll is not None else get_settings().worker_poll_sec
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="yeoun-inline-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        try:
            reset_stuck_jobs()
        except Exception:
            log.exception("reset_stuck_jobs_failed")
        while not self._stop.is_set():
            try:
                worked = run_one()
            except Exception:
                log.exception("worker_loop_error")
                worked = False
            if not worked:
                self._stop.wait(self.poll)


def main() -> None:  # pragma: no cover - 별도 프로세스 실행
    from app.logging_setup import setup_logging

    setup_logging()
    log.info("worker started")
    w = InlineWorker()
    w._loop()


if __name__ == "__main__":  # pragma: no cover
    main()
