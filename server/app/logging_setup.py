"""로그 설정. 자막·파일명·토큰 같은 민감 정보는 남기지 않는다.

- uvicorn 기본 접근 로그는 끄고, 경로 대신 라우트 템플릿(/api/spaces/{space_id}/clips)만 남긴다.
- 혹시 메시지에 토큰 모양 문자열이 섞여도 RedactFilter가 가린다.
"""

from __future__ import annotations

import logging
import re

from app.config import get_settings

_PATTERNS = [
    (re.compile(r"(/api/record/)[A-Za-z0-9_\-]{10,}"), r"\1***"),
    (re.compile(r"(/r/)[A-Za-z0-9_\-]{10,}"), r"\1***"),
    (re.compile(r"(/invite/)[A-Za-z0-9_\-]{10,}"), r"\1***"),
    (re.compile(r"(sig=)[A-Za-z0-9_\-]+"), r"\1***"),
    (
        re.compile(
            r"(?i)(api[_-]?key|authorization|x-api-key|password|token)(['\"]?\s*[:=]\s*['\"]?)[^\s'\",]+"
        ),
        r"\1\2***",
    ),
    (re.compile(r"sk-[A-Za-z0-9_\-]{10,}"), "sk-***"),
]


def redact(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        red = redact(msg)
        if red != msg:
            record.msg = red
            record.args = ()
        return True


def setup_logging() -> None:
    s = get_settings()
    root = logging.getLogger()
    if getattr(root, "_yeoun_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactFilter())
    root.handlers = [handler]
    root.setLevel(s.log_level.upper())
    # 외부 라이브러리의 상세 로그(요청 URL·본문 가능)는 줄인다
    for noisy in ("httpx", "httpx2", "httpcore", "botocore", "boto3", "urllib3", "multipart", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True
    root._yeoun_configured = True  # type: ignore[attr-defined]
