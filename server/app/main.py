"""여운 API 서버."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.errors import error_body, install_error_handlers
from app.logging_setup import setup_logging
from app.security import crypto

log = logging.getLogger("yeoun.http")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-yeoun-request"

ROUTERS = ["meta", "auth", "spaces", "assets", "media"]


class RequestGuardMiddleware(BaseHTTPMiddleware):
    """CSRF 방지(사용자 정의 헤더 요구) + 보안 헤더 + 민감 정보 없는 접근 로그."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse(status_code=403, content=error_body("csrf_failed"))
            # 본문을 다 받기 전에 너무 큰 요청을 거절한다 (파일 상한 + 여유 2MB)
            limit = (max(get_settings().max_file_mb, 12) + 2) * 1024 * 1024
            try:
                length = int(request.headers.get("content-length") or 0)
            except ValueError:
                length = 0
            if length > limit:
                return JSONResponse(status_code=413, content=error_body("file_too_large"))
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/media/"):
            response.headers.setdefault("Cache-Control", "no-store")
        route = request.scope.get("route")
        template = getattr(route, "path", "(unmatched)")
        log.info(
            "%s %s %s %.0fms",
            request.method,
            template,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    s = get_settings()
    crypto.master_key()  # staging/production에서 키가 없으면 여기서 멈춘다
    worker = None
    if s.worker_inline and s.env != "test":
        from app.worker import InlineWorker

        worker = InlineWorker()
        worker.start()
    log.info("started env=%s storage=%s inline_worker=%s", s.env, s.storage, bool(worker))
    try:
        yield
    finally:
        if worker:
            worker.stop()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Yeoun API",
        version=s.version,
        lifespan=lifespan,
        docs_url="/api/docs" if s.is_dev_like else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if s.is_dev_like else None,
    )
    install_error_handlers(app)
    app.add_middleware(RequestGuardMiddleware)

    import importlib

    for name in ROUTERS:
        module = importlib.import_module(f"app.routers.{name}")
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
