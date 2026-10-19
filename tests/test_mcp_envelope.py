import httpx
import pytest

from agent.catalogue import Catalogue, ToolSpec
from agent.mcp_client import McpClient, McpError, client_from_env


def test_rpc_error_on_200():
    def handler(req):
        if req.url.path.endswith("/api/mcp"):
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "tool_not_available"}},
            )
        return httpx.Response(404)

    c = McpClient(base_url="https://example.test", email="t@t", password="x")
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    c._token = "t"
    c._initialized = True
    with pytest.raises(McpError, match="tool_not_available"):
        c.rpc("tools/call", {"name": "X.list", "arguments": {}})
    c.close()


def test_notify_202():
    c = McpClient(base_url="https://example.test", email="t@t", password="x")
    c._http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(202, content=b"")))
    c._token = "t"
    assert c.rpc("notifications/initialized", {}, notification=True) is None
    c.close()


def test_token_only_ensure_token():
    c = McpClient(base_url="https://example.test", token="seat-token")
    assert c.ensure_token() == "seat-token"
    assert not c._can_relogin()
    with pytest.raises(McpError, match="login unavailable"):
        c.login()
    c.close()


def test_client_from_env_prefers_token(monkeypatch):
    monkeypatch.setenv("AGENTSWITCH_BASE_URL", "https://example.test")
    monkeypatch.setenv("AGENTSWITCH_TOKEN", "seat-token")
    monkeypatch.delenv("AS_PASSWORD", raising=False)
    c = client_from_env()
    assert c.base_url == "https://example.test"
    assert c.ensure_token() == "seat-token"
    c.close()


def test_client_from_env_token_requires_agentswitch_base_url(monkeypatch):
    monkeypatch.setenv("AGENTSWITCH_TOKEN", "seat-token")
    monkeypatch.delenv("AGENTSWITCH_BASE_URL", raising=False)
    monkeypatch.setenv("AS_BASE_URL", "https://public.example")  # must not be used for token auth
    with pytest.raises(RuntimeError, match="AGENTSWITCH_BASE_URL"):
        client_from_env()


def test_client_from_env_local_requires_base_url(monkeypatch):
    monkeypatch.delenv("AGENTSWITCH_TOKEN", raising=False)
    monkeypatch.delenv("AGENTSWITCH_BASE_URL", raising=False)
    monkeypatch.delenv("AS_BASE_URL", raising=False)
    monkeypatch.setenv("AS_PASSWORD", "secret")
    with pytest.raises(RuntimeError, match="AS_BASE_URL"):
        client_from_env()


def test_client_from_env_local_uses_as_base_url(monkeypatch):
    monkeypatch.delenv("AGENTSWITCH_TOKEN", raising=False)
    monkeypatch.delenv("AGENTSWITCH_BASE_URL", raising=False)
    monkeypatch.setenv("AS_BASE_URL", "https://local.example")
    monkeypatch.setenv("AS_EMAIL", "team13@test")
    monkeypatch.setenv("AS_PASSWORD", "secret")
    c = client_from_env()
    assert c.base_url == "https://local.example"
    assert c.email == "team13@test"
    c.close()


def test_closed_schema():
    cat = Catalogue(tools={
        "Attendance.list": ToolSpec(
            name="Attendance.list",
            description="list",
            input_schema={
                "type": "object",
                "properties": {"date": {"type": "string"}, "limit": {"type": "integer"}},
                "additionalProperties": False,
            },
        )
    })
    with pytest.raises(ValueError, match="closed_schema"):
        cat.validate_args("Attendance.list", {"date": "2026-09-15", "check_in": "2026-09-15"})
