"""Fan out `notifications/tools/list_changed` to connected SSE clients.

The ProcessManager fires a state-change event whenever a server is
enabled, disabled, or idle-killed. This module subscribes to that
event and pushes a JSON-RPC notification into every live SSE session
queue so the client sees the HOT set shrink (or grow) without having
to poll `tools/list`.

Streamable HTTP clients are not covered by this fan-out: their
response queue is tied to an in-flight POST and the JSON-only shape of
``send_via_stream_bridge`` cannot deliver a separate event. Those
clients pick up the new set on the next tools/list they issue, which
is frequent enough in practice (Claude Code, Gemini CLI) for the loss
to be negligible.
"""
from __future__ import annotations

import asyncio

from ...core.logging import get_logger
from ...core.process_manager import get_process_manager
from .session_queue import _session_queues_lock, _session_response_queues

logger = get_logger(__name__)

# Spec shape for MCP notifications/tools/list_changed — no id, no params.
TOOLS_LIST_CHANGED_NOTIFICATION: dict = {
    "jsonrpc": "2.0",
    "method": "notifications/tools/list_changed",
}


async def fan_out_tools_list_changed(event: str, server_name: str) -> None:
    """ProcessManager listener: push tools/list_changed to every SSE session."""
    async with _session_queues_lock:
        queues = [entry[0] for entry in _session_response_queues.values()]

    if not queues:
        logger.debug(
            "tools/list_changed (%s on %s) — no SSE sessions to notify",
            event,
            server_name,
        )
        return

    logger.info(
        "Fanning out tools/list_changed (%s on %s) to %d SSE session(s)",
        event,
        server_name,
        len(queues),
    )
    for queue in queues:
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
