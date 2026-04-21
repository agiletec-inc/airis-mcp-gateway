"""
Regression tests for the fan-out of notifications/tools/list_changed.

``fan_out_tools_list_changed`` is registered with ProcessManager at
startup. When a server leaves (or joins) the HOT set every live
client session must receive a properly-shaped JSON-RPC notification
so the client re-requests tools/list. Two session kinds are covered:
classic SSE sessions (``session_queue``) and Streamable HTTP bridges
(``gateway_stream_bridge``).
"""
from __future__ import annotations

import asyncio

import pytest

from app.api.endpoints import gateway_stream_bridge, session_queue
from app.api.endpoints.tools_list_notifier import (
    TOOLS_LIST_CHANGED_NOTIFICATION,
    fan_out_tools_list_changed,
    install_tools_list_changed_fanout,
)
from app.core.process_manager import ProcessManager


class _FakeBridge:
    """Minimal stand-in for StreamBridgeSession for fan-out tests."""

    def __init__(self, session_id: str, closed: bool = False) -> None:
        self.public_session_id = session_id
        self.closed = closed
        self.response_queue: asyncio.Queue = asyncio.Queue()


@pytest.fixture(autouse=True)
def clean_session_queues():
    """Reset the module-level session registries between tests."""
    session_queue._session_response_queues.clear()
    gateway_stream_bridge._stream_bridge_sessions.clear()
    yield
    session_queue._session_response_queues.clear()
    gateway_stream_bridge._stream_bridge_sessions.clear()


@pytest.mark.asyncio
async def test_fan_out_pushes_notification_to_all_sse_session_queues():
    q1 = await session_queue.get_response_queue("sess-1")
    q2 = await session_queue.get_response_queue("sess-2")

    await fan_out_tools_list_changed("idle_killed", "stripe")

    assert q1.qsize() == 1
    assert q2.qsize() == 1
    assert q1.get_nowait() == TOOLS_LIST_CHANGED_NOTIFICATION
    assert q2.get_nowait() == TOOLS_LIST_CHANGED_NOTIFICATION


@pytest.mark.asyncio
async def test_fan_out_also_pushes_to_stream_bridge_sessions():
    """Streamable HTTP bridges must receive the same notification shape."""
    b1 = _FakeBridge("bridge-1")
    b2 = _FakeBridge("bridge-2")
    gateway_stream_bridge._stream_bridge_sessions["bridge-1"] = b1  # type: ignore[assignment]
    gateway_stream_bridge._stream_bridge_sessions["bridge-2"] = b2  # type: ignore[assignment]

    await fan_out_tools_list_changed("enabled", "context7")

    assert b1.response_queue.qsize() == 1
    assert b2.response_queue.qsize() == 1
    assert b1.response_queue.get_nowait() == TOOLS_LIST_CHANGED_NOTIFICATION
    assert b2.response_queue.get_nowait() == TOOLS_LIST_CHANGED_NOTIFICATION


@pytest.mark.asyncio
async def test_fan_out_skips_closed_stream_bridges():
    """A bridge that has already been closed is not a valid delivery target."""
    alive = _FakeBridge("alive")
    dead = _FakeBridge("dead", closed=True)
    gateway_stream_bridge._stream_bridge_sessions["alive"] = alive  # type: ignore[assignment]
    gateway_stream_bridge._stream_bridge_sessions["dead"] = dead  # type: ignore[assignment]

    await fan_out_tools_list_changed("disabled", "stripe")

    assert alive.response_queue.qsize() == 1
    assert dead.response_queue.qsize() == 0


@pytest.mark.asyncio
async def test_fan_out_delivers_to_mixed_sse_and_bridge_sessions():
    """Both channel types must fire in a single call."""
    sse = await session_queue.get_response_queue("sse-1")
    bridge = _FakeBridge("bridge-1")
    gateway_stream_bridge._stream_bridge_sessions["bridge-1"] = bridge  # type: ignore[assignment]

    await fan_out_tools_list_changed("idle_killed", "supabase")

    assert sse.qsize() == 1
    assert bridge.response_queue.qsize() == 1


@pytest.mark.asyncio
async def test_notification_shape_matches_mcp_spec():
    """Must be a pure notification: jsonrpc + method, no id, no params."""
    assert TOOLS_LIST_CHANGED_NOTIFICATION == {
        "jsonrpc": "2.0",
        "method": "notifications/tools/list_changed",
    }


@pytest.mark.asyncio
async def test_fan_out_is_noop_without_sessions():
    # Must not raise when nobody is subscribed.
    await fan_out_tools_list_changed("idle_killed", "stripe")


@pytest.mark.asyncio
async def test_install_registers_listener_on_process_manager(monkeypatch):
    pm = ProcessManager()
    from app.api.endpoints import tools_list_notifier
    monkeypatch.setattr(tools_list_notifier, "get_process_manager", lambda: pm)

    install_tools_list_changed_fanout()
    assert fan_out_tools_list_changed in pm._state_change_listeners

    # Idempotent — a second install does not duplicate the listener.
    install_tools_list_changed_fanout()
    assert pm._state_change_listeners.count(fan_out_tools_list_changed) == 1
