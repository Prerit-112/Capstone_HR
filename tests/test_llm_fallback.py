from agent.llm import _is_retryable_limit, resolve_api_key, resolve_fallbacks, resolve_model


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


def test_retry_429():
    class RateLimitError(Exception):
        pass

    assert _is_retryable_limit(RateLimitError("Error code: 429 quota"))


def test_no_retry_on_sig():
    class BadRequestError(Exception):
        pass

    err = BadRequestError("Error code: 400 - thought_signature missing in functionCall parts")
    assert not _is_retryable_limit(err)
