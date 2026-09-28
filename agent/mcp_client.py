"""AgentSwitch MCP client.

Wire contracts from the course brief §6:
- JSON-RPC 2.0 over POST /api/mcp, protocol 2025-11-25
- JSON-RPC errors return HTTP 200; failure is in the envelope
- Only authentication answers at the HTTP layer (401)
- Argument schemas are closed (additionalProperties rejected)
- No batching, no SSE
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

PROTOCOL_VERSION = "2025-11-25"


class McpError(Exception):
    """JSON-RPC or transport failure with a structured payload."""

    def __init__(self, message: str, *, code: int | None = None, data: Any = None, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.data = data
        self.http_status = http_status


@dataclass
class WireEntry:
    ts: float
    method: str
    request: dict[str, Any]
    http_status: int
    response: dict[str, Any] | None
    error: str | None = None


@dataclass
class McpClient:
    base_url: str
    email: str
    password: str
    client_name: str = "team13-hr-agent"
    client_version: str = "0.1.0"
    timeout: float = 60.0
    wire_log: list[WireEntry] = field(default_factory=list)

    _token: str | None = field(default=None, init=False, repr=False)
    _rpc_id: int = field(default=0, init=False)
    _http: httpx.Client | None = field(default=None, init=False, repr=False)
    _initialized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def _http_client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- auth ---

    def login(self) -> str:
        http = self._http_client()
        r = http.post(
            f"{self.base_url}/api/auth/login",
            json={"email": self.email, "password": self.password},
        )
        if r.status_code != 200:
            raise McpError(f"login failed: HTTP {r.status_code} {r.text[:300]}", http_status=r.status_code)
        body = r.json()
        token = body.get("token")
        if not token:
            raise McpError(f"login response missing token: {body!r}")
        self._token = token
        self._initialized = False
        return token

    def ensure_token(self) -> str:
        if not self._token:
            self.login()
        assert self._token
        return self._token

    def me(self) -> dict[str, Any]:
        http = self._http_client()
        token = self.ensure_token()
        r = http.get(f"{self.base_url}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 401:
            self.login()
            r = http.get(
                f"{self.base_url}/api/auth/me",
                headers={"Authorization": f"Bearer {self._token}"},
            )
        if r.status_code != 200:
            raise McpError(f"/api/auth/me failed: HTTP {r.status_code}", http_status=r.status_code)
        return r.json()

    # --- JSON-RPC ---

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def _redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Shallow copy for the wire log; never stores the bearer token."""
        return json.loads(json.dumps(payload, default=str))

    def rpc(self, method: str, params: dict[str, Any] | None = None, *, notification: bool = False) -> Any:
        token = self.ensure_token()
        http = self._http_client()
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if not notification:
            body["id"] = self._next_id()
        if params is not None:
            body["params"] = params

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        def _post() -> httpx.Response:
            return http.post(f"{self.base_url}/api/mcp", headers=headers, json=body)

        r = _post()
        if r.status_code == 401:
            self.login()
            headers["Authorization"] = f"Bearer {self._token}"
            r = _post()

        entry = WireEntry(
            ts=time.time(),
            method=method,
            request=self._redact(body),
            http_status=r.status_code,
            response=None,
        )

        if notification:
            # Notifications may return 200 or 202 with empty body.
            if r.status_code not in (200, 202, 204):
                entry.error = r.text[:500]
                self.wire_log.append(entry)
                raise McpError(
                    f"MCP HTTP {r.status_code} for {method}: {r.text[:300]}",
                    http_status=r.status_code,
                )
            entry.response = {"notification": True, "http_status": r.status_code}
            self.wire_log.append(entry)
            return None

        if r.status_code != 200:
            entry.error = r.text[:500]
            self.wire_log.append(entry)
            raise McpError(
                f"MCP HTTP {r.status_code} for {method}: {r.text[:300]}",
                http_status=r.status_code,
            )

        try:
            envelope = r.json()
        except Exception as e:
            entry.error = f"non-json body: {r.text[:300]}"
            self.wire_log.append(entry)
            raise McpError(f"MCP returned non-JSON for {method}: {e}") from e

        entry.response = self._redact(envelope)
        self.wire_log.append(entry)

        # Brief §6: failure is in the envelope even when HTTP is 200.
        if "error" in envelope and envelope["error"] is not None:
            err = envelope["error"]
            raise McpError(
                err.get("message", str(err)),
                code=err.get("code"),
                data=err.get("data"),
                http_status=200,
            )
        if "result" not in envelope:
            raise McpError(f"MCP response missing result for {method}: {envelope!r}")
        return envelope["result"]

    def initialize(self) -> dict[str, Any]:
        result = self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": self.client_version},
            },
        )
        # Spec: client acknowledges; brief notes notifications/initialized.
        self.rpc("notifications/initialized", {}, notification=True)
        self._initialized = True
        return result

    def ensure_initialized(self) -> None:
        self.ensure_token()
        if not self._initialized:
            self.initialize()

    def tools_list(self) -> list[dict[str, Any]]:
        self.ensure_initialized()
        result = self.rpc("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else result
        if not isinstance(tools, list):
            raise McpError(f"unexpected tools/list shape: {type(result)}")
        return tools

    def tools_call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.ensure_initialized()
        result = self.rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        # MCP tools/call often wraps content; unwrap common shapes.
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list) and content:
                texts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(part.get("text", ""))
                if texts:
                    joined = "\n".join(texts)
                    try:
                        return json.loads(joined)
                    except json.JSONDecodeError:
                        return {"_text": joined, "_raw": result}
            if result.get("isError"):
                raise McpError(f"tool {name} isError", data=result)
        if isinstance(result, dict) and result.get("isError"):
            raise McpError(f"tool {name} isError", data=result)
        return result

    def list_all(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        page_size: int = 100,
        max_pages: int = 50,
        items_key: str = "data",
    ) -> dict[str, Any]:
        """Paginate *.list tools. Returns {items, total, pages, partial_error}."""
        args = dict(arguments or {})
        args.setdefault("limit", page_size)
        args.setdefault("offset", 0)
        items: list[Any] = []
        total: int | None = None
        pages = 0
        partial_error: str | None = None

        while pages < max_pages:
            try:
                page = self.tools_call(tool_name, args)
            except McpError as e:
                partial_error = str(e)
                break
            pages += 1
            batch: list[Any]
            if isinstance(page, dict):
                if total is None:
                    total = page.get("total")
                batch = page.get(items_key) or page.get("items") or page.get("results") or []
                if not isinstance(batch, list):
                    # Single-object or unexpected — stop.
                    if not items and page:
                        return {"items": [page], "total": 1, "pages": pages, "partial_error": None}
                    break
            elif isinstance(page, list):
                batch = page
            else:
                partial_error = f"unexpected list page type: {type(page)}"
                break

            items.extend(batch)
            if not batch:
                break
            if total is not None and len(items) >= total:
                break
            if len(batch) < args["limit"]:
                break
            args["offset"] = args.get("offset", 0) + args["limit"]

        return {
            "items": items,
            "total": total if total is not None else len(items),
            "pages": pages,
            "partial_error": partial_error,
        }

    def clear_wire_log(self) -> None:
        self.wire_log.clear()

    def dump_wire_log(self) -> list[dict[str, Any]]:
        return [
            {
                "ts": e.ts,
                "method": e.method,
                "http_status": e.http_status,
                "request": e.request,
                "response": e.response,
                "error": e.error,
            }
            for e in self.wire_log
        ]
