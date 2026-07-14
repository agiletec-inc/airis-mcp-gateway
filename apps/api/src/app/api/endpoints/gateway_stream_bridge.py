"""Bridge a Streamable HTTP MCP client to a Docker Gateway SSE session.

The Docker MCP Gateway only speaks classic SSE (``GET /sse`` keeps a
long-lived response open, POSTs are delivered back as events on that
stream). Streamable HTTP clients (Codex RMCP, Claude Code's streaming
transport, etc.) want to send POSTs and receive a single HTTP response
per request, optionally reusing the same session via the
``Mcp-Session-Id`` header.

This module owns the glue that makes both worlds work together:

* :class:`StreamBridgeSession` holds the httpx client, the open SSE
  stream, and a background reader task that pumps Gateway SSE events
  into an in-memory ``asyncio.Queue``.
* :func:`_send_via_stream_bridge` is the entry point used by the
  JSON-RPC proxy to POST a payload and wait for the matching response.
* :func:`cleanup_stale_stream_bridges` is the periodic janitor that
  tears down idle bridges so each one's file descriptors, queue, and
  reader task are not leaked over time.

Everything else — the SSE proxy, the handlers, the routes — imports
from here instead of re-implementing httpx session plumbing.
"""
from __future__ import annotations

import asyncio
import json
import time as _time_module
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import Request, Response

from ...core.behavior_compiler import compile_instructions
from ...core.config import settings
from ...core.logging import get_logger
from .sse_protocol import format_sse_event, parse_sse_json
from .tool_shaping import apply_prompts_merging, apply_schema_partitioning

logger = get_logger(__name__)


# HTTP client timeouts match the SSE proxy. SSE streams are long-lived so
# ``read`` is deliberately large — connection / write / pool still need
# short timeouts to catch actually-broken upstreams quickly.
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 120.0
WRITE_TIMEOUT = 10.0
POOL_TIMEOUT = 10.0

STREAM_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT,
    read=READ_TIMEOUT,
    write=WRITE_TIMEOUT,
    pool=POOL_TIMEOUT,
)

# After opening a new bridge the Docker Gateway sometimes rejects the
# first POST with "session not found". Let the backend session settle
# before we send anything.
STREAM_BRIDGE_READY_DELAY = 0.3

# Idle bridges are reaped after 15 minutes. This matches a typical MCP
# client reconnect window while bounding memory on a long-running gateway.
_STREAM_BRIDGE_TTL_SECONDS = 900


# Shared state for active bridges. The dict and lock are module-level so
# that cleanup_stale_stream_bridges() and the lifespan cleanup task can
# reach them without constructing a singleton wrapper.
_stream_bridge_sessions: dict[str, "StreamBridgeSession"] = {}
_stream_bridge_lock = asyncio.Lock()


@dataclass
class StreamBridgeSession:
    """Bridges a Streamable HTTP client session onto a Gateway SSE session."""

    public_session_id: str
    backend_session_id: str
    client: httpx.AsyncClient
    stream_context: Any
    stream_response: httpx.Response
    response_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    closed: bool = False
    reader_task: Optional[asyncio.Task] = None
    # ids currently owned by a live send_via_stream_bridge() waiter on this
    # session. Lets a concurrent caller distinguish "still owned by a live
    # sibling — keep requeuing" from "orphaned, nobody left to claim it —
    # drop it" without a magic retry-count heuristic (a fixed count can't
    # tell "several live bystanders" from "no owner left" — see #210 review).
    pending_response_ids: set = field(default_factory=set)
    created_at: float = field(default_factory=_time_module.monotonic)
    last_activity: float = field(default_factory=_time_module.monotonic)

    def touch(self) -> None:
        """Record that the client or backend just used this session."""
        self.last_activity = _time_module.monotonic()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.reader_task is not None:
            self.reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.reader_task
        await self.stream_response.aclose()
        await self.stream_context.__aexit__(None, None, None)
        await self.client.aclose()


def stream_session_header_name() -> str:
    return "Mcp-Session-Id"


def get_stream_session_id(request: Request) -> Optional[str]:
    return request.headers.get(stream_session_header_name())


def extract_gateway_session_id(endpoint_url: str) -> Optional[str]:
    parsed = urlparse(endpoint_url)
    session_ids = parse_qs(parsed.query).get("sessionid")
    if session_ids:
        return session_ids[0]
    return None


def get_response_message_id(payload: Any) -> Any:
    """Derive the id a caller should wait for on a given response payload."""
    if not isinstance(payload, dict):
        return None
    if "id" in payload:
        return payload.get("id")
    if payload.get("method") == "notifications/initialized":
        return "__initialized__"
    return None


async def _transform_gateway_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the same shaping the SSE proxy does to Gateway-sourced JSON."""
    if isinstance(payload, dict) and "result" in payload and "tools" in payload.get("result", {}):
        payload = await apply_schema_partitioning(payload)

    if isinstance(payload, dict) and "result" in payload and "prompts" in payload.get("result", {}):
        payload = await apply_prompts_merging(payload)

    is_initialize_response = (
        isinstance(payload, dict)
        and "result" in payload
        and isinstance(payload.get("result"), dict)
        and "protocolVersion" in payload.get("result", {})
    )
    if is_initialize_response:
        from ...core.mcp_config_loader import load_mcp_config

        server_configs = load_mcp_config()
        payload["result"]["instructions"] = compile_instructions(server_configs)

    return payload


async def _stream_bridge_reader(
    session: StreamBridgeSession,
    lines_iter: Any,
) -> None:
    """Drain the Gateway SSE stream and forward JSON payloads to the queue."""
    pending_lines: list[str] = []
    try:
        while True:
            try:
                raw_line = await lines_iter.__anext__()
            except StopAsyncIteration:
                break
            line = raw_line.strip()
            if line == "":
                payload = parse_sse_json(pending_lines)
                pending_lines = []
                if payload is None:
                    continue
                transformed = await _transform_gateway_payload(payload)
                await session.response_queue.put(transformed)
            else:
                pending_lines.append(line)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — best-effort fan-out
        logger.warning(
            "Stream bridge reader stopped for %s: %s",
            session.public_session_id,
            exc,
        )
    finally:
        if pending_lines:
            payload = parse_sse_json(pending_lines)
            if payload is not None:
                transformed = await _transform_gateway_payload(payload)
                await session.response_queue.put(transformed)
        await session.response_queue.put(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": "Gateway SSE bridge disconnected"},
            }
        )


async def _open_stream_bridge_session() -> StreamBridgeSession:
    """Create a persistent bridge session for Streamable HTTP clients."""
    client = httpx.AsyncClient(timeout=STREAM_TIMEOUT)
    gateway_sse_url = f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse"
    stream_context = client.stream(
        "GET",
        gateway_sse_url,
        headers={"Accept": "text/event-stream"},
    )
    try:
        stream_response = await stream_context.__aenter__()
        lines_iter = stream_response.aiter_lines()
        backend_session_id: Optional[str] = None
        while True:
            try:
                raw_line = await asyncio.wait_for(lines_iter.__anext__(), timeout=10.0)
            except (StopAsyncIteration, asyncio.TimeoutError):
                break
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str.startswith("{") or data_str.startswith("["):
                continue
            backend_session_id = extract_gateway_session_id(data_str)
            if backend_session_id:
                break
        if not backend_session_id:
            raise RuntimeError("Gateway did not provide an SSE session id")

        session = StreamBridgeSession(
            public_session_id=f"airis-{uuid.uuid4().hex}",
            backend_session_id=backend_session_id,
            client=client,
            stream_context=stream_context,
            stream_response=stream_response,
        )
        session.reader_task = asyncio.create_task(
            _stream_bridge_reader(session, lines_iter)
        )
        return session
    except Exception:
        await stream_context.__aexit__(None, None, None)
        await client.aclose()
        raise


async def get_or_create_stream_bridge_session(
    request: Request, *, create: bool
) -> Optional[StreamBridgeSession]:
    public_session_id = get_stream_session_id(request)
    if public_session_id:
        async with _stream_bridge_lock:
            return _stream_bridge_sessions.get(public_session_id)
    if not create:
        return None
    session = await _open_stream_bridge_session()
    async with _stream_bridge_lock:
        _stream_bridge_sessions[session.public_session_id] = session
    return session


async def close_stream_bridge_session(public_session_id: str) -> None:
    async with _stream_bridge_lock:
        session = _stream_bridge_sessions.pop(public_session_id, None)
    if session is not None:
        await session.close()


async def delete_stream_bridge_session(request: Request) -> Response:
    public_session_id = get_stream_session_id(request)
    if not public_session_id:
        return Response(status_code=204)
    await close_stream_bridge_session(public_session_id)
    return Response(status_code=204)


async def send_via_stream_bridge(
    request: Request,
    rpc_request: Dict[str, Any],
) -> Response:
    """Forward a single JSON-RPC call via the backing SSE session."""
    create_session = rpc_request.get("method") == "initialize"
    try:
        session = await get_or_create_stream_bridge_session(
            request, create=create_session
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to open stream bridge session: %s", exc)
        return Response(
            content=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_request.get("id"),
                    "error": {
                        "code": -32000,
                        "message": f"Failed to open Gateway session: {exc}",
                    },
                }
            ),
            status_code=502,
            media_type="application/json",
        )
    if session is None:
        return Response(
            content=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_request.get("id"),
                    "error": {
                        "code": -32001,
                        "message": "Unknown or expired MCP session",
                    },
                }
            ),
            status_code=400,
            media_type="application/json",
        )

    session.touch()

    # The Docker Gateway can briefly reject the first POST after the SSE
    # stream opens with "session not found". Let the backend settle first.
    session_age = _time_module.monotonic() - session.created_at
    if session_age < STREAM_BRIDGE_READY_DELAY:
        await asyncio.sleep(STREAM_BRIDGE_READY_DELAY - session_age)

    target_url = (
        f"{settings.MCP_GATEWAY_URL.rstrip('/')}/sse?sessionid={session.backend_session_id}"
    )
    expected_id = get_response_message_id(rpc_request)
    # Register this call as a live waiter for expected_id BEFORE dispatching
    # the POST — not after it returns — so that by the time any response
    # could possibly reach the shared queue (which requires a real Gateway
    # round trip: this POST lands, the Gateway processes it, and its SSE
    # reader forwards the answer), this id is already known to be live. A
    # concurrent sibling call's requeue decision below can then trust
    # membership in this set instead of a magic retry count, which can't
    # tell "several live bystanders" from "no owner left" (see #210 review).
    if expected_id is not None:
        session.pending_response_ids.add(expected_id)

    try:
        try:
            response = await session.client.post(
                target_url,
                json=rpc_request,
                headers={"Content-Type": "application/json"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send bridged request to Gateway: %s", exc)
            return Response(
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_request.get("id"),
                        "error": {
                            "code": -32000,
                            "message": f"Failed to reach Gateway session: {exc}",
                        },
                    }
                ),
                status_code=502,
                media_type="application/json",
                headers={stream_session_header_name(): session.public_session_id},
            )
        if response.status_code not in (200, 202):
            return Response(
                content=response.text,
                status_code=response.status_code,
                media_type=response.headers.get("content-type"),
            )

        if "id" not in rpc_request:
            return Response(
                status_code=202,
                headers={stream_session_header_name(): session.public_session_id},
            )

        # Buffer server-to-client notifications that arrive before the matching
        # response. The MCP Streamable HTTP spec lets the server answer a single
        # POST with either a JSON body or an SSE event stream; we use the SSE
        # path only when there's at least one notification to deliver, so the
        # fast path for routine tool calls stays plain JSON.
        pending_notifications: list[dict] = []

        while True:
            try:
                payload = await asyncio.wait_for(
                    session.response_queue.get(),
                    timeout=settings.TOOL_CALL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                return Response(
                    content=json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": rpc_request.get("id"),
                            "error": {
                                "code": -32001,
                                "message": "Timed out waiting for Gateway response",
                            },
                        }
                    ),
                    status_code=504,
                    media_type="application/json",
                    headers={stream_session_header_name(): session.public_session_id},
                )
            if (
                isinstance(payload, dict)
                and payload.get("error", {}).get("message") == "Gateway SSE bridge disconnected"
            ):
                await close_stream_bridge_session(session.public_session_id)
                return Response(
                    content=json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": rpc_request.get("id"),
                            "error": {
                                "code": -32000,
                                "message": "Gateway session disconnected",
                            },
                        }
                    ),
                    status_code=502,
                    media_type="application/json",
                )

            if (
                isinstance(payload, dict)
                and "method" in payload
                and "id" not in payload
                and get_response_message_id(payload) != expected_id
            ):
                # Server-to-client notification that is not the synthetic
                # `notifications/initialized` bridge marker — buffer for SSE delivery.
                pending_notifications.append(payload)
                continue

            if expected_id is None or get_response_message_id(payload) == expected_id:
                if pending_notifications:
                    body_parts = [
                        format_sse_event(n) for n in pending_notifications
                    ]
                    body_parts.append(format_sse_event(payload))
                    return Response(
                        content=b"".join(body_parts),
                        status_code=200,
                        media_type="text/event-stream",
                        headers={stream_session_header_name(): session.public_session_id},
                    )
                return Response(
                    content=json.dumps(payload),
                    status_code=200,
                    media_type="application/json",
                    headers={stream_session_header_name(): session.public_session_id},
                )

            # Response for a different concurrent call on the same session
            # (e.g. two overlapping tools/call requests sharing one
            # Mcp-Session-Id). Re-queue it only if that id is still owned by
            # a live waiter — otherwise its owner already timed out or
            # disconnected and requeuing would spin forever with no other
            # reader ever going to claim it.
            payload_id = get_response_message_id(payload)
            if payload_id in session.pending_response_ids:
                await session.response_queue.put(payload)
            else:
                logger.warning(
                    "Dropping orphaned Gateway response for session %s: id=%r has no live waiter",
                    session.public_session_id,
                    payload_id,
                )
            continue
    finally:
        session.pending_response_ids.discard(expected_id)


async def cleanup_stale_stream_bridges() -> int:
    """Tear down StreamBridgeSession entries that have been idle for too long.

    Each bridge holds an open httpx.AsyncClient and an SSE reader task, so a
    leaked bridge costs a file descriptor, a task, and a queue. Idle ones
    need to be closed proactively — clients may disconnect without sending
    a DELETE and a long-running gateway would otherwise accumulate them.

    Returns:
        Number of bridges closed. Callers typically log this so a leak
        that keeps the count climbing is visible in operations.
    """
    now = _time_module.monotonic()
    threshold = now - _STREAM_BRIDGE_TTL_SECONDS
    to_close: list[str] = []
    async with _stream_bridge_lock:
        for sid, session in _stream_bridge_sessions.items():
            if session.closed or session.last_activity < threshold:
                to_close.append(sid)

    removed = 0
    for sid in to_close:
        try:
            await close_stream_bridge_session(sid)
            removed += 1
            logger.info("Cleaned up stale stream bridge session: %s", sid)
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            logger.warning("Error closing stale stream bridge %s: %s", sid, exc)
    return removed


def get_stream_bridge_count() -> int:
    """Number of live StreamBridgeSession entries (monitoring helper)."""
    return len(_stream_bridge_sessions)
