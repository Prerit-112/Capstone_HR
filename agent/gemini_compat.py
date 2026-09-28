"""Gemini OpenAI-compat helpers (thought signatures, etc.)."""
from __future__ import annotations

from typing import Any


def serialize_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    """Serialize tool_calls for the next request, preserving Gemini thought_signature.

    Gemini 3.x returns extra_content.google.thought_signature on function calls.
    Omitting it on the next turn → HTTP 400 INVALID_ARGUMENT.
    https://ai.google.dev/gemini-api/docs/thought-signatures
    """
    serialized: list[dict[str, Any]] = []
    for tc in tool_calls:
        if hasattr(tc, "model_dump"):
            dumped = tc.model_dump(exclude_none=True)
            extra = getattr(tc, "model_extra", None) or {}
            if "extra_content" in extra and "extra_content" not in dumped:
                dumped["extra_content"] = extra["extra_content"]
        elif isinstance(tc, dict):
            dumped = dict(tc)
        else:
            dumped = {
                "id": getattr(tc, "id", ""),
                "type": "function",
                "function": {
                    "name": getattr(getattr(tc, "function", None), "name", ""),
                    "arguments": getattr(getattr(tc, "function", None), "arguments", "{}") or "{}",
                },
            }
        serialized.append(dumped)
    return serialized


def has_thought_signature(tool_call: dict[str, Any]) -> bool:
    extra = tool_call.get("extra_content") or {}
    google = extra.get("google") or {}
    return bool(google.get("thought_signature"))
