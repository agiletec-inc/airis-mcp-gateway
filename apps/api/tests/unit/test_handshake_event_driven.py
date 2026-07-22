"""
Regression tests for issue #194: the MCP initialize->initialized auto-init
fallback in `_proxy_jsonrpc_request()` must wait on the real Gateway
initialize response instead of racing a fixed sleep budget.

Follows the FakeRequest / monkeypatch pattern from
test_mcp_proxy_error_injection.py and test_cold_tool_auto_discovery.py.
"""

import asyncio
import json
import time

import pytest

from app.api.endpoints import mcp_proxy
from app.core.dynamic_mcp import DynamicMCP
from app.core.process_manager import ProcessManager


class _FakeURL:
    """Minimal starlette.URL stand-in for _build_gateway_jsonrpc_url()."""

    def __init__(self, path: str = "/v1/mcp/", query: str = ""):
        self.path = path
        self.query = query


class FakeRequest:
    """Minimal Starlette-Request stand-in with a sessionid (classic SSE proxy path)."""

    def __init__(self, payload: dict, session_id: str):
        self._body = json.dumps(payload).encode()
        self.query_params = {"sessionid": session_id}
        self.url = _FakeURL()
        self.headers: dict = {}

    async def body(self) -> bytes:
        return self._body


class FakeResponse:
    def __init__(self, status_code: int = 202, content: bytes = b"{}"):
        self.status_code = status_code
        self.content = content
        self.headers: dict = {}


def _make_fake_async_client(call_log: list):
    """A minimal httpx.AsyncClient stand-in that records POSTs instead of
    hitting a real network. Used for both the auto-init handshake's
    `init_client` and the final passthrough `client` in
    `_proxy_jsonrpc_request()` — both go through `httpx.AsyncClient(...)`.
    """

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, **kwargs):
            call_log.append((time.monotonic(), url, kwargs.get("json")))
            return FakeResponse()

    return FakeAsyncClient


@pytest.fixture
def wired(monkeypatch):
    pm = ProcessManager()
    pm._initialized = True
    monkeypatch.setattr(mcp_proxy, "get_process_manager", lambda: pm)

    dmcp = DynamicMCP()
    monkeypatch.setattr(mcp_proxy, "get_dynamic_mcp", lambda: dmcp)
    return pm, dmcp


@pytest.mark.asyncio
async def test_auto_init_waits_for_slow_initialize_response(wired, monkeypatch):
    """
    A slow upstream whose initialize response arrives well after the old
    fixed 0.15s budget must not be raced past: the handshake has to
    actually observe the response before sending `notifications/initialized`.

    `proxy_sse_stream()` is the coroutine that normally sets the
    session's initialize event when the real Gateway response arrives on
    the client's SSE stream (see `is_initialize_response` handling in
    mcp_proxy.py). Here we simulate that arriving late, directly via the
    same `_get_initialize_event()` hook it uses.
    """
    session_id = "SESSIONSLOW1"
    mcp_proxy._initialized_sessions.discard(session_id)
    mcp_proxy._session_initialize_events.pop(session_id, None)

    call_log: list = []
    monkeypatch.setattr(
        mcp_proxy.httpx, "AsyncClient", _make_fake_async_client(call_log)
    )

    slow_delay = 0.5  # far past the old fixed 0.15s + 0.10s budget

    async def deliver_slow_initialize_response():
        await asyncio.sleep(slow_delay)
        mcp_proxy._get_initialize_event(session_id).set()

    delivery_task = asyncio.create_task(deliver_slow_initialize_response())

    payload = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "some-unregistered-tool", "arguments": {}},
    }

    start = time.monotonic()
    resp = await mcp_proxy._proxy_jsonrpc_request(FakeRequest(payload, session_id))
    elapsed = time.monotonic() - start
    await delivery_task

    assert resp.status_code == 202

    # The handshake must have actually waited for the (slow) event rather
    # than racing past it with a fixed sleep budget that would have
    # completed almost instantly relative to `slow_delay`.
    assert elapsed >= slow_delay, (
        f"handshake completed in {elapsed:.3f}s, before the simulated slow "
        f"initialize response at {slow_delay}s — it raced instead of waiting"
    )
    assert session_id in mcp_proxy._initialized_sessions

    # Sanity: both handshake steps were actually sent to the Gateway.
    methods = [j.get("method") for _, _, j in call_log if j]
    assert "initialize" in methods
    assert "notifications/initialized" in methods


@pytest.mark.asyncio
async def test_auto_init_timeout_proceeds_when_initialize_response_never_arrives(
    wired, monkeypatch
):
    """If the initialize event is never signaled (e.g. the Gateway silently
    drops it), the handshake must still proceed after its bounded timeout
    rather than hanging forever."""
    session_id = "SESSIONNEVER1"
    mcp_proxy._initialized_sessions.discard(session_id)
    mcp_proxy._session_initialize_events.pop(session_id, None)

    call_log: list = []
    monkeypatch.setattr(
        mcp_proxy.httpx, "AsyncClient", _make_fake_async_client(call_log)
    )
    # Shrink the bounded wait so the test doesn't take 10s.
    monkeypatch.setattr(mcp_proxy, "INIT_HANDSHAKE_TIMEOUT", 0.2)

    payload = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "some-unregistered-tool", "arguments": {}},
    }

    resp = await mcp_proxy._proxy_jsonrpc_request(FakeRequest(payload, session_id))

    assert resp.status_code == 202
    # Handshake proceeds best-effort after timing out.
    assert session_id in mcp_proxy._initialized_sessions
