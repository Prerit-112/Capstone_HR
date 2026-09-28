import httpx
import pytest

from agent.catalogue import Catalogue, ToolSpec
from agent.mcp_client import McpClient, McpError


def test_rpc_error_on_200():
    def handler(req: httpx.Request) -> httpx.Response:
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
