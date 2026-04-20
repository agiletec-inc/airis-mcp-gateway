"""
Regression test for the SSE fan-out of notifications/tools/list_changed.

`fan_out_tools_list_changed` is registered with ProcessManager at
startup. When a server leaves (or joins) the HOT set, every live SSE
session queue must receive a properly-shaped JSON-RPC notification so
the client re-requests tools/list.
"""
from __future__ import annotations

import asyncio

import pytest

from app.api.endpoints import session_queue
from app.api.endpoints.tools_list_notifier import (
    TOOLS_LIST_CHANGED_NOTIFICATION,
    fan_out_tools_list_changed,
    install_tools_list_changed_fanout,
)
from app.core.process_manager import ProcessManager


@pytest.fixture(autouse=True)
def clean_session_queues():
    """Reset the module-level session queue registry between tests."""
    session_queue._session_response_queues.clear()
    yield
    session_queue._session_response_queues.clear()


@pytest.mark.asyncio
async def test_fan_out_pushes_notification_to_all_session_queues():
    q1 = await session_queue.get_response_queue("sess-1")
    q2 = await session_queue.get_response_queue("sess-2")

    await fan_out_tools_list_changed("idle_killed", "stripe")

    assert q1.qsize() == 1
    assert q2.qsize() == 1
    assert q1.get_nowait() == TOOLS_LIST_CHANGED_NOTIFICATION
    assert q2.get_nowait() == TOOLS_LIST_CHANGED_NOTIFICATION


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
