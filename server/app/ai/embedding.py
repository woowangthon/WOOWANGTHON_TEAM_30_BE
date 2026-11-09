"""임베딩 어댑터 (openai, gemini, none). none이면 BM25만 쓴다."""

from __future__ import annotations

import array

import httpx

from app.ai.base import ProviderError, api_key
from app.config import get_settings


def pack(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def unpack(blob: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(blob)
    return a.tolist()


class NoEmbedder:
    name = "none"
    model = None
    live = False

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        return None


class OpenAIEmbedder:
    name = "openai"
    live = True

    def __init__(self, key: str):
        self.key = key
        self.model = get_settings().openai_embedding_model

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = [t or " " for t in texts[i : i + 64]]
            try:
                r = httpx.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json={"model": self.model, "input": batch},
                    timeout=get_settings().llm_timeout_sec,
                )
            except httpx.HTTPError as e:
                raise ProviderError("http_error", type(e).__name__) from e
            if r.status_code != 200:
                raise ProviderError("http_error", f"status={r.status_code}")
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out += [d["embedding"] for d in data]
        return out


class GeminiEmbedder:
    name = "gemini"
    live = True

    def __init__(self, key: str):
        self.key = key
        self.model = get_settings().gemini_embedding_model

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            batch = texts[i : i + 50]
            body = {
                "requests": [
                    {"model": f"models/{self.model}", "content": {"parts": [{"text": t or " "}]}}
                    for t in batch
                ]
            }
            try:
                r = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents",
                    headers={"x-goog-api-key": self.key},
                    json=body,
                    timeout=get_settings().llm_timeout_sec,
                )
            except httpx.HTTPError as e:
                raise ProviderError("http_error", type(e).__name__) from e
            if r.status_code != 200:
                raise ProviderError("http_error", f"status={r.status_code}")
            out += [e["values"] for e in r.json()["embeddings"]]
        return out


def build(name: str):
    if name == "openai":
        key = api_key("openai")
        if not key:
            raise ProviderError("not_configured")
        return OpenAIEmbedder(key)
    if name == "gemini":
        key = api_key("gemini")
        if not key:
            raise ProviderError("not_configured")
        return GeminiEmbedder(key)
    return NoEmbedder()
