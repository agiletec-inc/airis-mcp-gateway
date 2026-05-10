"""Session response queue lifecycle for the MCP SSE proxy.

MCP SSE transport requires that responses be written back to the client via
the long-lived GET /sse stream rather than the HTTP response body of the
POST that carried the request. To bridge an incoming JSON-RPC call to the
right SSE stream, the proxy keeps a per-session ``asyncio.Queue`` and the
SSE stream drains it.

This module owns that lifecycle exclusively:

* ``get_response_queue`` — lazily create a queue for a session id
* ``remove_response_queue`` — drop a queue when a session ends
* ``cleanup_stale_queues`` — drop queues that have been idle for TTL seconds
* ``get_session_queue_count`` — monitoring helper

Keeping the responsibility in its own module lets the rest of the proxy
import these primitives without pulling in the full SSE/bridge/handler
graph — and lets us test the lifecycle in isolation (see
``tests/unit/test_session_queue.py``).
"""
from __future__ import annotations

import asyncio
import time as _time_module

from ...core.logging import get_logger

logger = get_logger(__name__)


# Session -> (queue, last_access_timestamp). last_access is refreshed on
# every get_response_queue() call so a busy session is never reaped by
# cleanup_stale_queues().
_session_response_queues: dict[str, tuple[asyncio.Queue, float]] = {}
_session_queues_lock = asyncio.Lock()

# 10 minutes. Short enough to bound memory on a long-running gateway,
# long enough to survive a brief client reconnect.
_SESSION_QUEUE_TTL_SECONDS = 600


async def get_response_queue(session_id: str) -> asyncio.Queue:
    """Get or create a response queue for a session (coroutine-safe)."""
    now = _time_module.time()
    async with _session_queues_lock:
        if session_id in _session_response_queues:
            queue, _ = _session_response_queues[session_id]
            _session_response_queues[session_id] = (queue, now)
            return queue
        queue: asyncio.Queue = asyncio.Queue()
        _session_response_queues[session_id] = (queue, now)
        return queue


async def remove_response_queue(session_id: str) -> None:
    """Remove a response queue when a session ends (coroutine-safe)."""
    async with _session_queues_lock:
        _session_response_queues.pop(session_id, None)


async def cleanup_stale_queues() -> int:
    """Drop queues whose last access is older than the TTL.

    Returns:
        Number of queues removed. The caller typically logs this so an
        operator can spot a leak where the count keeps growing.
    """
    now = _time_module.time()
    threshold = now - _SESSION_QUEUE_TTL_SECONDS
    removed = 0
    async with _session_queues_lock:
        stale_sessions = [
            sid
            for sid, (_, last_access) in _session_response_queues.items()
            if last_access < threshold
        ]
        for sid in stale_sessions:
            _session_response_queues.pop(sid, None)
            logger.info("Cleaned up stale session queue: %s", sid)
            removed += 1
    return removed


def get_session_queue_count() -> int:
    """Return current number of session queues (monitoring helper)."""
    return len(_session_response_queues)
