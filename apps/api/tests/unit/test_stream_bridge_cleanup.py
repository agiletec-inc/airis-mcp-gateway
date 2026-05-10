"""Tests for stream bridge session cleanup (issue #111)."""
from __future__ import annotations

import time as _time

import pytest

from app.api.endpoints import mcp_proxy


class _FakeBridge:
    """Minimal stand-in for StreamBridgeSession.

    Only exposes the attributes that cleanup_stale_stream_bridges touches,
    plus an async close() that records the call.
    """

    def __init__(self, public_session_id: str, last_activity: float, closed: bool = False):
        self.public_session_id = public_session_id
        self.last_activity = last_activity
        self.closed = closed
        self._close_calls = 0

    async def close(self) -> None:
        self._close_calls += 1
        self.closed = True


@pytest.fixture(autouse=True)
def clear_bridge_state():
    mcp_proxy._stream_bridge_sessions.clear()
    yield
    mcp_proxy._stream_bridge_sessions.clear()


@pytest.mark.asyncio
async def test_cleanup_removes_idle_bridge(monkeypatch):
    now = _time.monotonic()
    fresh = _FakeBridge("fresh", last_activity=now)
    stale = _FakeBridge("stale", last_activity=now - 10_000)
    mcp_proxy._stream_bridge_sessions["fresh"] = fresh  # type: ignore[assignment]
    mcp_proxy._stream_bridge_sessions["stale"] = stale  # type: ignore[assignment]

    removed = await mcp_proxy.cleanup_stale_stream_bridges()

    assert removed == 1
    assert "stale" not in mcp_proxy._stream_bridge_sessions
    assert "fresh" in mcp_proxy._stream_bridge_sessions
    assert stale._close_calls == 1


@pytest.mark.asyncio
async def test_cleanup_removes_already_closed_bridge():
    now = _time.monotonic()
    closed = _FakeBridge("closed", last_activity=now, closed=True)
    mcp_proxy._stream_bridge_sessions["closed"] = closed  # type: ignore[assignment]

    removed = await mcp_proxy.cleanup_stale_stream_bridges()

    assert removed == 1
    assert "closed" not in mcp_proxy._stream_bridge_sessions


@pytest.mark.asyncio
async def test_cleanup_noop_on_empty_store():
    assert await mcp_proxy.cleanup_stale_stream_bridges() == 0


def test_get_stream_bridge_count_tracks_dict_size():
    assert mcp_proxy.get_stream_bridge_count() == 0
    mcp_proxy._stream_bridge_sessions["a"] = _FakeBridge("a", 0.0)  # type: ignore[assignment]
    assert mcp_proxy.get_stream_bridge_count() == 1
