"""Reproduce issue #210: response demux drops out-of-order concurrent replies.

``StreamBridgeSession`` holds a single shared ``response_queue``. When two
``send_via_stream_bridge()`` calls run concurrently against the same session
(two ``tools/call`` requests sharing one ``Mcp-Session-Id``), each awaits
``session.response_queue.get()`` in a loop looking for the JSON-RPC response
whose ``id`` matches its own ``expected_id``.

A payload that HAS an ``id`` but belongs to the OTHER concurrent call
(``id != expected_id``) matches neither:

* the "is my response" branch (`expected_id is None or get_response_message_id(payload) == expected_id`)
* nor the "is a notification" branch (`"method" in payload and "id" not in payload`)

so it falls through the ``while True`` loop and is silently dropped forever —
never requeued for the caller that actually owns it. That caller then blocks
until ``settings.TOOL_CALL_TIMEOUT`` and returns a 504, even though the
Gateway already answered.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.api.endpoints import gateway_stream_bridge
from app.core.config import settings


class _FakeHeaders(dict):
    def get(self, key, default=None):  # noqa: D401 - dict.get shadow for Request-like API
        return super().get(key, default)


class _FakeRequest:
    """Minimal stand-in exposing only what get_stream_session_id() touches."""

    def __init__(self, session_id: str):
        self.headers = _FakeHeaders({gateway_stream_bridge.stream_session_header_name(): session_id})


class _FakeGatewayResponse:
    def __init__(self, status_code: int = 202):
        self.status_code = status_code
        self.text = ""
        self.headers: dict = {}


class _FakeGatewayClient:
    """Stands in for httpx.AsyncClient — the POST is accepted (202), the
    actual JSON-RPC response arrives later via the shared response_queue,
    exactly like the real Gateway's SSE-fan-out flow."""

    async def post(self, *args, **kwargs):
        return _FakeGatewayResponse(status_code=202)


@pytest.fixture(autouse=True)
def clear_bridge_state():
    gateway_stream_bridge._stream_bridge_sessions.clear()
    yield
    gateway_stream_bridge._stream_bridge_sessions.clear()


def _make_session(public_session_id: str) -> gateway_stream_bridge.StreamBridgeSession:
    return gateway_stream_bridge.StreamBridgeSession(
        public_session_id=public_session_id,
        backend_session_id="backend-session-xyz",
        client=_FakeGatewayClient(),
        stream_context=object(),
        stream_response=object(),
        # Session "born" long ago so send_via_stream_bridge() skips the
        # STREAM_BRIDGE_READY_DELAY settle-sleep for both callers. Without
        # this, the two callers' sleep durations differ by the few
        # microseconds between their monotonic() reads, which flips which
        # one reaches the response_queue first and can mask the race this
        # test targets.
        created_at=0.0,
    )


@pytest.mark.asyncio
async def test_concurrent_calls_each_get_their_own_response(monkeypatch):
    """Two concurrent tools/call requests on ONE shared session must each
    receive their own matching JSON-RPC response — not a 504 timeout and
    not the other call's payload — even when the Gateway answers out of
    order (id=2's answer lands on the shared queue before id=1's)."""
    # Keep the timeout short: this test asserts what happens once both
    # answers are already sitting in the queue, so a slow real Gateway is
    # not involved. If the bug is present, the affected call will genuinely
    # block for the full timeout before returning 504.
    monkeypatch.setattr(settings, "TOOL_CALL_TIMEOUT", 1.0)

    session = _make_session("airis-demux-test")
    gateway_stream_bridge._stream_bridge_sessions[session.public_session_id] = session

    # Simulate the Gateway answering call B (id=2) before call A (id=1),
    # e.g. because B's tool happened to resolve faster server-side.
    await session.response_queue.put({"jsonrpc": "2.0", "id": 2, "result": {"for": "B"}})
    await session.response_queue.put({"jsonrpc": "2.0", "id": 1, "result": {"for": "A"}})

    request = _FakeRequest(session.public_session_id)

    call_a = gateway_stream_bridge.send_via_stream_bridge(
        request, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "a"}}
    )
    call_b = gateway_stream_bridge.send_via_stream_bridge(
        request, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "b"}}
    )

    response_a, response_b = await asyncio.gather(call_a, call_b)

    body_a = json.loads(response_a.body)
    body_b = json.loads(response_b.body)

    assert response_a.status_code == 200, (
        f"caller A (id=1) did not get its response: status={response_a.status_code} body={body_a}"
    )
    assert response_b.status_code == 200, (
        f"caller B (id=2) did not get its response: status={response_b.status_code} body={body_b}"
    )
    assert body_a.get("id") == 1
    assert body_a.get("result") == {"for": "A"}
    assert body_b.get("id") == 2
    assert body_b.get("result") == {"for": "B"}
