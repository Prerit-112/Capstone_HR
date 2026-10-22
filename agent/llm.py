"""LLM client config — platform OpenAI-compatible first, Gemini locally."""
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

# Cumulative billed tokens per task (prompt+completion across steps).
# ~40k × 11 ≈ 440k, leaving headroom under a ~500k run budget.
DEFAULT_TASK_TOKEN_LIMIT = 40_000


class BudgetExhaustedError(Exception):
    """Hard run/token budget exhausted — do not retry; stop remaining suite tasks."""

    def __init__(self, message: str, *, cause: BaseException | None = None):
        super().__init__(message)
        self.cause = cause


def is_budget_exhausted(exc: BaseException) -> bool:
    """True when the platform signals the run token budget is gone (not a soft RPM 429)."""
    msg = str(exc).lower()
    tokens = (
        "budget_exhausted",
        "budget exhausted",
        "token budget",
        "tokens budget",
        "run budget",
        "quota_exceeded_budget",
    )
    return any(tok in msg for tok in tokens)


def resolve_task_token_limit() -> int:
    """Max cumulative usage tokens (prompt+completion) per task before stop+recover."""
    raw = (os.getenv("LLM_TASK_TOKEN_LIMIT") or "").strip()
    if raw:
        try:
            return max(1_000, int(raw))
        except ValueError:
            pass
    return DEFAULT_TASK_TOKEN_LIMIT


def estimate_message_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> int:
    """Rough token estimate (chars/4) for budget enforcement without a tokenizer."""
    total_chars = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total_chars += len(content)
        elif content is not None:
            total_chars += len(str(content))
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                fn = tc.get("function") or {}
                total_chars += len(str(fn.get("name") or ""))
                total_chars += len(str(fn.get("arguments") or ""))
            else:
                total_chars += 64
    if tools:
        total_chars += len(str(tools))
    return max(1, total_chars // 4)


def _platform_openai() -> bool:
    """True when the official harness (or any explicit OpenAI endpoint) is configured."""
    return bool((os.getenv("OPENAI_BASE_URL") or "").strip() and (os.getenv("OPENAI_API_KEY") or "").strip())


def resolve_api_key() -> str:
    if _platform_openai():
        return (os.getenv("OPENAI_API_KEY") or "").strip()
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()


def resolve_model() -> str:
    if _platform_openai():
        # Never fall back to a Gemini model name on the platform endpoint.
        return (
            (os.getenv("OPENAI_MODEL") or "").strip()
            or "agentswitch-default"
        )
    return (
        os.getenv("GEMINI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_GEMINI_MODEL
    ).strip()


def resolve_fallbacks(primary: str | None = None) -> list[str]:
    """Ordered unique model list: primary first, then optional fallbacks."""
    primary = (primary or resolve_model()).strip()
    raw = (os.getenv("GEMINI_MODEL_FALLBACKS") or "").strip()
    if raw:
        extras = [m.strip() for m in raw.split(",") if m.strip()]
    elif _platform_openai() or (os.getenv("OPENAI_BASE_URL") or "").strip():
        # Official harness / explicit OpenAI endpoint: stay on one model.
        extras = []
    else:
        extras = list(DEFAULT_FALLBACKS)
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


def resolve_retries_per_model() -> int:
    raw = (os.getenv("LLM_RETRIES_PER_MODEL") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    # Platform has a single model and late-suite rate limits; retry harder there.
    return 5 if _platform_openai() else 3


def resolve_backoff_seconds() -> float:
    raw = (os.getenv("LLM_BACKOFF_SECONDS") or "").strip()
    if raw:
        try:
            return max(0.1, float(raw))
        except ValueError:
            pass
    return 3.0 if _platform_openai() else 2.0


def build_llm_client() -> OpenAI:
    key = resolve_api_key()
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY (official harness) or GEMINI_API_KEY (local)")
    return OpenAI(api_key=key, base_url=resolve_base_url())


def _is_retryable_limit(exc: BaseException) -> bool:
    """Backward-compatible name: rate/quota style limits."""
    return _is_retryable(exc)


def _is_retryable(exc: BaseException) -> bool:
    """True for transient LLM/transport failures worth retrying on the same model.

    Hard budget exhaustion is never retryable — retries would burn the remaining run.
    """
    if isinstance(exc, BudgetExhaustedError) or is_budget_exhausted(exc):
        return False

    name = type(exc).__name__
    msg = str(exc).lower()

    if name in {
        "RateLimitError",
        "InternalServerError",
        "APITimeoutError",
        "APIConnectionError",
        "TimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
    }:
        return True

    if name in {"APIStatusError", "APIError", "HTTPStatusError"}:
        if any(code in msg for code in ("429", "500", "502", "503", "504")):
            return True
        if any(tok in msg for tok in ("quota", "rate", "high demand", "unavailable", "overloaded", "capacity")):
            return True

    retry_tokens = (
        "429",
        "resource_exhausted",
        "rate limit",
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "server error",
        "bad gateway",
        "gateway timeout",
        "high demand",
        "unavailable",
    )
    if any(tok in msg for tok in retry_tokens):
        return True
    return False


def chat_with_fallback(
    client: OpenAI,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    models: list[str] | None = None,
    temperature: float = 0.1,
    retries_per_model: int | None = None,
    backoff_seconds: float | None = None,
) -> tuple[Any, str]:
    """Create a chat completion, retrying transient errors then rotating models.

    Returns (response, model_used).
    Raises BudgetExhaustedError without retry when the platform signals budget_exhausted.
    """
    chain = models or resolve_fallbacks()
    retries = retries_per_model if retries_per_model is not None else resolve_retries_per_model()
    backoff = backoff_seconds if backoff_seconds is not None else resolve_backoff_seconds()
    last_err: BaseException | None = None
    for model in chain:
        for attempt in range(retries):
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
                if is_budget_exhausted(e):
                    raise BudgetExhaustedError(str(e), cause=e) from e
                if not _is_retryable(e):
                    raise
                # Stay on this model for all retries; only then try the next fallback.
                if attempt + 1 < retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                time.sleep(backoff * (attempt + 1))
                break  # exhausted retries for this model → next model
    assert last_err is not None
    if is_budget_exhausted(last_err):
        raise BudgetExhaustedError(str(last_err), cause=last_err) from last_err
    raise last_err
