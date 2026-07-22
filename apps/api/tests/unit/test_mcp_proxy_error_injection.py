"""
Regression test for the -32602 error-injection path on the MCP Streamable HTTP
proxy (`_proxy_jsonrpc_request`).

The REST endpoint `/process/tools/call` already re-hydrates -32602/-32000 errors
with the tool's full input schema (see test_process_mcp_error_injection.py). But
real MCP clients (Claude Code, Codex) never hit that REST path — they POST
`tools/call` to `/mcp/`, which routes through `_proxy_jsonrpc_request`. That path
returned the backend validation error verbatim, so the lazy-schema "self-heal on
retry" contract silently did nothing for actual clients.

These tests pin the contract on the Streamable HTTP (no-sessionid) path.
"""

import json

import pytest

from app.api.endpoints import mcp_proxy
from app.core.dynamic_mcp import DynamicMCP, ToolInfo
from app.core.process_manager import ProcessManager

RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "libraryName": {"type": "string"},
    },
    "required": ["query", "libraryName"],
}


class FakeRequest:
    """Minimal Starlette-Request stand-in for _proxy_jsonrpc_request."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()
        # no sessionid → Streamable HTTP branch
        self.query_params: dict = {}

    async def body(self) -> bytes:
        return self._body


@pytest.fixture
def wired(monkeypatch):
    """Stub ProcessManager + DynamicMCP singletons used by mcp_proxy."""
    pm = ProcessManager()
    pm._initialized = True
    pm._tool_to_server = {"resolve-library-id": "context7"}
    monkeypatch.setattr("app.api.endpoints.mcp_proxy.get_process_manager", lambda: pm)

    dmcp = DynamicMCP()
    dmcp._tools["resolve-library-id"] = ToolInfo(
        name="resolve-library-id",
        server="context7",
        description="Resolve a library name to a Context7 ID",
        input_schema=RESOLVE_SCHEMA,
        source="process",
    )
    # mcp_proxy.get_dynamic_mcp is used on the auto-discovery path; the shared
    # inject_schema_on_validation_error helper reads app.core.dynamic_mcp's.
    monkeypatch.setattr("app.api.endpoints.mcp_proxy.get_dynamic_mcp", lambda: dmcp)
    monkeypatch.setattr("app.core.dynamic_mcp.get_dynamic_mcp", lambda: dmcp)
    return pm


def _tools_call(name: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


@pytest.mark.asyncio
async def test_streamable_http_injects_schema_on_32602(wired, monkeypatch):
    pm = wired

    async def fake_call_tool(name, arguments):
        return {
            "jsonrpc": "2.0",
            "id": 7,
            "error": {"code": -32602, "message": "Invalid arguments for tool"},
        }

    monkeypatch.setattr(pm, "call_tool", fake_call_tool)

    resp = await mcp_proxy._proxy_jsonrpc_request(
        FakeRequest(_tools_call("resolve-library-id", {"query": "fastapi"}))
    )

    body = json.loads(resp.body)
    assert body["error"]["code"] == -32602
    # The full schema must be injected so the caller can self-heal on retry.
    assert "Full Schema" in body["error"]["message"]
    assert "libraryName" in body["error"]["message"]
    assert body["error"]["hint"].startswith("Retry")


@pytest.mark.asyncio
async def test_streamable_http_passes_through_non_validation_error(wired, monkeypatch):
    pm = wired

    async def fake_call_tool(name, arguments):
        return {
            "jsonrpc": "2.0",
            "id": 7,
            "error": {"code": -32601, "message": "Method not found"},
        }

    monkeypatch.setattr(pm, "call_tool", fake_call_tool)

    resp = await mcp_proxy._proxy_jsonrpc_request(
        FakeRequest(_tools_call("resolve-library-id", {}))
    )

    body = json.loads(resp.body)
    assert body["error"]["code"] == -32601
    assert "Full Schema" not in body["error"]["message"]
    assert "hint" not in body["error"]


@pytest.mark.asyncio
async def test_streamable_http_success_is_untouched(wired, monkeypatch):
    pm = wired

    async def fake_call_tool(name, arguments):
        return {
            "jsonrpc": "2.0",
            "id": 7,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }

    monkeypatch.setattr(pm, "call_tool", fake_call_tool)

    resp = await mcp_proxy._proxy_jsonrpc_request(
        FakeRequest(
            _tools_call("resolve-library-id", {"query": "x", "libraryName": "x"})
        )
    )

    body = json.loads(resp.body)
    assert "error" not in body
    assert body["result"]["content"][0]["text"] == "ok"
