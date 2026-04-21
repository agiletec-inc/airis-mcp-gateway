"""Fan out `notifications/tools/list_changed` to connected clients.

The ProcessManager fires a state-change event whenever a server is
enabled, disabled, or idle-killed. This module subscribes to that
event and pushes a JSON-RPC notification into every live client
session so clients see the HOT set shrink (or grow) without polling
``tools/list``.

Two session kinds are fanned out to:

* **Classic SSE sessions** — notifications are pushed into the
  per-session ``asyncio.Queue`` kept in :mod:`session_queue`. The SSE
  streaming loop drains the queue and writes each payload out as an
  SSE event directly.
* **Streamable HTTP bridges** — notifications are pushed into the
  ``StreamBridgeSession.response_queue``. A waiting POST accumulates
  them and, on the matching response, emits a ``text/event-stream``
  response that carries the buffered notifications followed by the
  request's actual result (see :func:`send_via_stream_bridge`).

If no POST is in flight on a given bridge when a notification fires,
it still sits in the queue and will be delivered on the next POST —
the client therefore never misses a list change, only its arrival
may be deferred a moment.
"""
from __future__ import annotations

import asyncio

from ...core.logging import get_logger
from ...core.process_manager import get_process_manager
from .gateway_stream_bridge import _stream_bridge_lock, _stream_bridge_sessions
from .session_queue import _session_queues_lock, _session_response_queues

logger = get_logger(__name__)

# Spec shape for MCP notifications/tools/list_changed — no id, no params.
TOOLS_LIST_CHANGED_NOTIFICATION: dict = {
    "jsonrpc": "2.0",
    "method": "notifications/tools/list_changed",
}


async def fan_out_tools_list_changed(event: str, server_name: str) -> None:
    """ProcessManager listener: notify every live session of the HOT-set change."""
    async with _session_queues_lock:
        sse_queues = [entry[0] for entry in _session_response_queues.values()]

    async with _stream_bridge_lock:
        bridge_queues = [
            session.response_queue
            for session in _stream_bridge_sessions.values()
            if not session.closed
        ]

    total = len(sse_queues) + len(bridge_queues)
    if total == 0:
        logger.debug(
            "tools/list_changed (%s on %s) — no sessions to notify",
            event,
            server_name,
        )
        return

    logger.info(
        "Fanning out tools/list_changed (%s on %s) to %d SSE + %d stream-bridge session(s)",
        event,
        server_name,
        len(sse_queues),
        len(bridge_queues),
    )
    for queue in sse_queues + bridge_queues:
        try:
            queue.put_nowait(TOOLS_LIST_CHANGED_NOTIFICATION)
        except asyncio.QueueFull:
            logger.warning(
                "session queue full while fanning out tools/list_changed"
            )


def install_tools_list_changed_fanout() -> None:
    """Register the fan-out listener with the global ProcessManager.

    Idempotent — safe to call from app startup even if the manager
    already has the listener installed (ProcessManager guards against
    duplicates).
    """
    get_process_manager().add_state_change_listener(fan_out_tools_list_changed)
