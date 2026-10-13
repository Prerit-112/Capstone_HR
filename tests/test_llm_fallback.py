import time

from agent.llm import (
    _is_retryable,
    _is_retryable_limit,
    chat_with_fallback,
    resolve_api_key,
    resolve_fallbacks,
    resolve_model,
    resolve_retries_per_model,
)


def test_fallback_order(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL_FALLBACKS", raising=False)
    chain = resolve_fallbacks("gemini-3.1-flash-lite")
    assert chain[0] == "gemini-3.1-flash-lite"
    assert "gemini-flash-lite-latest" in chain


def test_platform_openai_no_gemini_fallbacks(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "agentswitch-default")
    monkeypatch.delenv("GEMINI_MODEL_FALLBACKS", raising=False)
    assert resolve_api_key() == "sk-test"
    assert resolve_model() == "agentswitch-default"
    assert resolve_fallbacks() == ["agentswitch-default"]


def test_platform_openai_missing_model_not_gemini(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert resolve_model() == "agentswitch-default"


def test_platform_retries_default_higher(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("LLM_RETRIES_PER_MODEL", raising=False)
    assert resolve_retries_per_model() == 5


def test_retry_429():
    class RateLimitError(Exception):
        pass

    assert _is_retryable_limit(RateLimitError("Error code: 429 quota"))
    assert _is_retryable(RateLimitError("Error code: 429 quota"))


def test_retry_timeout_and_connection():
    class APITimeoutError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    assert _is_retryable(APITimeoutError("Request timed out"))
    assert _is_retryable(APIConnectionError("connection reset by peer"))
    assert _is_retryable(RuntimeError("Error code: 503 - unavailable"))


def test_no_retry_on_sig():
    class BadRequestError(Exception):
        pass

    err = BadRequestError("Error code: 400 - thought_signature missing in functionCall parts")
    assert not _is_retryable_limit(err)
    assert not _is_retryable(err)


def test_chat_retries_same_model_then_succeeds(monkeypatch):
    class RateLimitError(Exception):
        pass

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise RateLimitError("Error code: 429 quota")
            return {"ok": True, "model": kwargs["model"]}

    class FakeClient:
        def __init__(self):
            self.chat = type("C", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
    client = FakeClient()
    resp, model = chat_with_fallback(
        client,
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        models=["agentswitch-default"],
        retries_per_model=5,
        backoff_seconds=0.01,
    )
    assert resp["ok"] is True
    assert model == "agentswitch-default"
    assert client.chat.completions.calls == 3


def test_chat_moves_to_fallback_after_retries(monkeypatch):
    class RateLimitError(Exception):
        pass

    class FakeCompletions:
        def __init__(self):
            self.models = []

        def create(self, **kwargs):
            self.models.append(kwargs["model"])
            if kwargs["model"] == "primary":
                raise RateLimitError("429")
            return {"ok": True}

    class FakeClient:
        def __init__(self):
            self.chat = type("C", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
    client = FakeClient()
    resp, model = chat_with_fallback(
        client,
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        models=["primary", "secondary"],
        retries_per_model=2,
        backoff_seconds=0.01,
    )
    assert resp["ok"] is True
    assert model == "secondary"
    assert client.chat.completions.models.count("primary") == 2
