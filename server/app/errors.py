"""API 오류. 모든 오류는 {"error": {"code": "...", "message_ko": "..."}} 형식으로 내려간다."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("yeoun.errors")

MESSAGES: dict[str, str] = {
    "bad_request": "요청을 처리할 수 없어요.",
    "invalid_input": "입력한 내용을 다시 확인해 주세요.",
    "unauthorized": "로그인이 필요해요.",
    "forbidden": "이 공간에 접근할 권한이 없어요.",
    "not_found": "찾을 수 없어요.",
    "conflict": "이미 처리된 요청이에요.",
    "rate_limited": "요청이 너무 잦아요. 잠시 후 다시 해 주세요.",
    "internal_error": "잠시 문제가 생겼어요. 조금 뒤 다시 해 주세요.",
    "csrf_failed": "보안 확인에 실패했어요. 페이지를 새로 고친 뒤 다시 해 주세요.",
    "email_taken": "이미 가입된 이메일이에요.",
    "invalid_credentials": "이메일 또는 비밀번호가 맞지 않아요.",
    "invite_required": "지금은 초대 코드가 있어야 가입할 수 있어요.",
    "invalid_invite": "초대 코드가 맞지 않아요.",
    "weak_password": "비밀번호는 8자 이상으로 정해 주세요.",
    "invalid_email": "이메일 형식을 확인해 주세요.",
    "consent_required": "자료를 올리기 전에 안내 문구를 확인하고 동의해 주세요.",
    "unsupported_file": "이 형식의 파일은 아직 올릴 수 없어요.",
    "file_too_large": "파일이 너무 커요.",
    "empty_file": "빈 파일이에요.",
    "space_quota_exceeded": "이 공간에 저장할 수 있는 용량을 다 썼어요.",
    "user_quota_exceeded": "테스트 기간에 올릴 수 있는 분량을 다 썼어요.",
    "chat_limit_reached": "오늘 대화할 수 있는 횟수를 다 썼어요. 내일 다시 만나요.",
    "sample_read_only": "샘플 공간은 체험용이라 바꿀 수 없어요.",
    "media_link_expired": "재생 링크가 만료됐어요. 화면을 새로 고쳐 주세요.",
    "link_expired": "녹음 링크가 만료됐거나 이미 사용됐어요. 보낸 분께 새 링크를 부탁해 주세요.",
    "consent_needed": "녹음을 시작하기 전에 안내를 읽고 동의해 주세요.",
    "stt_unavailable": "음성 인식이 아직 꺼져 있어요. 글로 적어 주세요.",
    "stt_failed": "음성을 글로 바꾸지 못했어요. 다시 해 주세요.",
    "confirm_mismatch": "입력한 이름이 공간 이름과 달라요.",
    "owner_required": "공간 소유자만 할 수 있어요.",
    "invite_invalid": "초대 링크가 만료됐거나 이미 사용됐어요.",
    "cannot_remove_owner": "소유자는 내보낼 수 없어요.",
    "processing_busy": "아직 처리 중이에요. 끝난 뒤 다시 해 주세요.",
    "story_not_found": "그 기억과 관련된 녹음을 찾지 못했어요. 녹음에 나오는 낱말(음식·장소·사람)로 다시 적어 주세요. 여운은 녹음에 없는 이야기는 지어내지 않아요.",
    "book_no_clips": "책을 만들 녹음이 아직 없어요. 녹음을 올리고 '목소리 확인'에서 그분의 목소리를 골라 주세요.",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message_ko: str | None = None):
        self.status = status
        self.code = code
        self.message_ko = message_ko or MESSAGES.get(code, MESSAGES["bad_request"])
        super().__init__(code)


def error_body(code: str, message_ko: str | None = None) -> dict:
    return {"error": {"code": code, "message_ko": message_ko or MESSAGES.get(code, MESSAGES["bad_request"])}}


def not_found() -> ApiError:
    return ApiError(404, "not_found")


def forbidden() -> ApiError:
    return ApiError(403, "forbidden")


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "bad_request",
    409: "conflict",
    413: "file_too_large",
    429: "rate_limited",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=error_body(exc.code, exc.message_ko))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 입력값 자체는 로그에 남기지 않는다 (민감 정보 가능)
        fields = [".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors()]
        log.info("validation_error fields=%s", fields)
        return JSONResponse(status_code=422, content=error_body("invalid_input"))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "bad_request")
        return JSONResponse(status_code=exc.status_code, content=error_body(code))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error type=%s", type(exc).__name__)
        return JSONResponse(status_code=500, content=error_body("internal_error"))
