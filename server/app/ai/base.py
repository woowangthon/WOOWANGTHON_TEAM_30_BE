"""AI 공급자 공통 정의.

모든 어댑터는 provider = mock | 실제 공급자 | auto 구조다. 키가 없거나, 정책상 쓸 수 없거나,
모델 가중치가 없으면 mock(규칙)으로 돌아가 전체 흐름이 멈추지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings


class ProviderError(Exception):
    """공급자 호출 실패. code: timeout | refusal | bad_output | http_error | model_missing | not_configured"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ProviderMeta:
    function: str
    name: str
    display_name: str
    is_external: bool
    trains_on_input: bool
    data_sent: str
    retention_note: str


DATA_SENT = {
    "stt": "오디오(녹음 파일)",
    "diarization": "오디오(녹음 파일)",
    "llm": "보낸 말, 후보 클립의 자막·날짜·태그",
    "embedding": "자막 텍스트, 보낸 말",
}

RETENTION = {
    "openai": "OpenAI API: 입력을 모델 학습에 쓰지 않음(기본 설정). 오남용 감시를 위해 최대 30일 보관 후 삭제(공급자 정책).",
    "anthropic": "Anthropic API: 입력을 모델 학습에 쓰지 않음(기본 설정). 공급자 정책에 따라 일정 기간 보관 후 삭제.",
    "gemini_free": "Gemini API 무료 등급: 입력이 구글 제품 개선(학습)과 사람 검토에 쓰일 수 있음.",
    "gemini_paid": "Gemini API 유료 등급: 입력을 제품 개선(학습)에 쓰지 않음. 오남용 감시를 위해 일정 기간 보관.",
    "local": "외부로 보내지 않음 (여운 서버 안에서 처리).",
}


def meta_for(function: str, name: str) -> ProviderMeta:
    s = get_settings()
    if name in ("mock", "none", "replay"):
        labels = {
            "mock": "기본 방식 (규칙 기반, 외부 전송 없음)",
            "none": "사용 안 함",
            "replay": "녹화된 응답 재생 (테스트용)",
        }
        return ProviderMeta(function, name, labels[name], False, False, "없음", RETENTION["local"])
    if name == "openai":
        model = {
            "stt": s.openai_stt_model,
            "diarization": s.openai_diarize_model,
            "llm": s.openai_llm_model,
            "embedding": s.openai_embedding_model,
        }[function]
        return ProviderMeta(
            function, name, f"OpenAI ({model})", True, False, DATA_SENT[function], RETENTION["openai"]
        )
    if name == "anthropic":
        return ProviderMeta(
            function,
            name,
            f"Anthropic Claude ({s.anthropic_model})",
            True,
            False,
            DATA_SENT[function],
            RETENTION["anthropic"],
        )
    if name == "gemini":
        free = s.gemini_tier == "free"
        model = s.gemini_embedding_model if function == "embedding" else s.gemini_model
        return ProviderMeta(
            function,
            name,
            f"Google Gemini ({model}, {'무료' if free else '유료'} 등급)",
            True,
            free,
            DATA_SENT[function],
            RETENTION["gemini_free" if free else "gemini_paid"],
        )
    raise ValueError(name)


def api_key(name: str) -> str | None:
    s = get_settings()
    secret = {"openai": s.openai_api_key, "anthropic": s.anthropic_api_key, "gemini": s.gemini_api_key}.get(
        name
    )
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None
