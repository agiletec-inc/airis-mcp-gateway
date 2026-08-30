"""Regression tests for exception details reported by CodeQL (CWE-209)."""

from __future__ import annotations

import json

import pytest

from app.api.endpoints import gateway_stream_bridge, mcp_proxy, sse_tools
from app.core import repo_indexer


class _Request:
    headers: dict[str, str] = {}


@pytest.mark.asyncio
async def test_stream_bridge_open_error_does_not_expose_exception(monkeypatch):
    secret = "upstream-secret-from-stack"

    async def fail(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(
        gateway_stream_bridge, "get_or_create_stream_bridge_session", fail
    )

    response = await gateway_stream_bridge.send_via_stream_bridge(
        _Request(), {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    )
    payload = json.loads(response.body)

    assert payload["error"]["message"] == "Failed to open Gateway session"
    assert secret not in response.body.decode()


@pytest.mark.asyncio
async def test_stream_bridge_post_error_does_not_expose_exception(monkeypatch):
    secret = "backend-hostname-and-token"

    class FailingClient:
        async def post(self, *args, **kwargs):
            raise RuntimeError(secret)

    session = gateway_stream_bridge.StreamBridgeSession(
        public_session_id="public",
        backend_session_id="backend",
        client=FailingClient(),
        stream_context=object(),
        stream_response=object(),
        created_at=0.0,
    )
    monkeypatch.setattr(
        gateway_stream_bridge,
        "get_or_create_stream_bridge_session",
        lambda *args, **kwargs: _async_value(session),
    )

    response = await gateway_stream_bridge.send_via_stream_bridge(
        _Request(), {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}
    )
    payload = json.loads(response.body)

    assert payload["error"]["message"] == "Failed to reach Gateway session"
    assert secret not in response.body.decode()


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_sse_stream_error_does_not_expose_exception(monkeypatch):
    secret = "internal-tool-discovery-path"

    async def fail():
        raise RuntimeError(secret)

    monkeypatch.setattr(sse_tools, "get_all_server_status", fail)
    event = await anext(sse_tools.sse_event_generator("client-1"))

    assert "Tool discovery stream failed" in event
    assert secret not in event


@pytest.mark.asyncio
async def test_docker_tool_error_does_not_expose_exception(monkeypatch):
    secret = "gateway-connection-string"

    class DynamicMCP:
        def parse_tool_reference(self, tool_ref):
            return "docker", "example-tool"

    class ProcessManager:
        def is_process_server(self, server_name):
            return False

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            raise RuntimeError(secret)

    monkeypatch.setattr(mcp_proxy, "get_dynamic_mcp", lambda: DynamicMCP())
    monkeypatch.setattr(mcp_proxy, "get_process_manager", lambda: ProcessManager())
    monkeypatch.setattr(mcp_proxy.httpx, "AsyncClient", lambda *args, **kwargs: FailingClient())

    response = await mcp_proxy.handle_airis_exec(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "params": {"arguments": {"tool": "docker:example-tool"}},
        },
        session_id="backend-session",
    )
    payload = json.loads(response.body)

    assert payload["error"]["message"] == "Docker gateway request failed"
    assert secret not in response.body.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "expected_message"),
    [
        (FileNotFoundError("/private/repository/path"), "Repository path was not found"),
        (RuntimeError("database password leaked"), "Repository indexing failed"),
    ],
)
async def test_repo_index_error_does_not_expose_exception(
    monkeypatch, exception, expected_message
):
    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(repo_indexer, "generate_repo_index", fail)
    response = await mcp_proxy.handle_airis_repo_index(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "params": {"arguments": {"repo_path": "/tmp/repo"}},
        }
    )
    payload = json.loads(response.body)

    assert payload["error"]["message"] == expected_message
    assert str(exception) not in response.body.decode()
