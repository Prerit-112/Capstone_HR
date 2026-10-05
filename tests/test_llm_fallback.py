from agent.llm import _is_retryable_limit, resolve_fallbacks


def test_fallback_order():
    chain = resolve_fallbacks("gemini-3.1-flash-lite")
    assert chain[0] == "gemini-3.1-flash-lite"
    assert "gemini-flash-lite-latest" in chain


def test_retry_429():
    class RateLimitError(Exception):
        pass

    assert _is_retryable_limit(RateLimitError("Error code: 429 quota"))


def test_no_retry_on_sig():
    class BadRequestError(Exception):
        pass

    err = BadRequestError("Error code: 400 - thought_signature missing in functionCall parts")
    assert not _is_retryable_limit(err)
