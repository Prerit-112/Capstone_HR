"""LLM client config — Gemini via OpenAI-compatible endpoint."""
from __future__ import annotations

import os
import time
from typing import Any

from openai import OpenAI

# https://ai.google.dev/gemini-api/docs/openai
GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Prefer Flash Lite for free-tier RPM/TPM; fall back when a model is 429/503.
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
DEFAULT_FALLBACKS = (
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
)


def resolve_api_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()


def resolve_model() -> str:
    return (
        os.getenv("GEMINI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_GEMINI_MODEL
    ).strip()


def resolve_fallbacks(primary: str | None = None) -> list[str]:
    """Ordered unique model list: primary first, then GEMINI_MODEL_FALLBACKS / defaults."""
    primary = (primary or resolve_model()).strip()
    raw = (os.getenv("GEMINI_MODEL_FALLBACKS") or "").strip()
    extras = [m.strip() for m in raw.split(",") if m.strip()] if raw else list(DEFAULT_FALLBACKS)
    out: list[str] = []
    for m in [primary, *extras]:
        if m and m not in out:
            out.append(m)
    return out


def resolve_base_url() -> str:
    explicit = (os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/") + "/"
    return GEMINI_OPENAI_BASE


def build_llm_client() -> OpenAI:
    key = resolve_api_key()
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY (or GOOGLE_API_KEY) in .env")
    return OpenAI(api_key=key, base_url=resolve_base_url())


def _is_retryable_limit(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    if name in {"RateLimitError", "InternalServerError", "APIStatusError"}:
        if "429" in msg or "503" in msg or "quota" in msg or "rate" in msg or "high demand" in msg or "unavailable" in msg:
            return True
    if "429" in msg or "resource_exhausted" in msg:
        return True
    return False


def chat_with_fallback(
    client: OpenAI,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    models: list[str] | None = None,
    temperature: float = 0.1,
    retries_per_model: int = 2,
    backoff_seconds: float = 2.0,
) -> tuple[Any, str]:
    """Create a chat completion, rotating models on 429/503.

    Returns (response, model_used).
    """
    chain = models or resolve_fallbacks()
    last_err: BaseException | None = None
    for model in chain:
        for attempt in range(retries_per_model):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                return client.chat.completions.create(**kwargs), model
            except Exception as e:
                last_err = e
                if not _is_retryable_limit(e):
                    raise
                # Brief backoff, then try again / next model.
                time.sleep(backoff_seconds * (attempt + 1))
                break  # next model after one backoff cycle per model attempt group
        # continue to next model after retries exhausted for this one
    assert last_err is not None
    raise last_err
