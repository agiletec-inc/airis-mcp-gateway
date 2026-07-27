"""SSE wire-format helpers.

Pure functions (plus one tiny buffer class) for encoding and decoding
Server-Sent Events. The rest of the proxy uses these primitives to bridge
between FastAPI StreamingResponse byte streams and in-memory JSON-RPC
payloads. No I/O, no session state — the contents of this module can be
unit-tested without a running event loop.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


class SSEEventBuffer:
    """Accumulates SSE lines and emits one complete event at a time."""

    def __init__(self) -> None:
        self.buffer: list[str] = []

    def add_line(self, line: str) -> Optional[str]:
        """Feed a raw SSE line and, if a full event just ended, return it.

        SSE events are terminated by a blank line. Comments (lines that
        start with ``:``) are emitted immediately because they are used
        as keepalives and must not be buffered.
        """
        if line.startswith(":"):
            # SSE comment (keepalive) — pass through immediately
            return f"{line}\n\n"
        if line == "":
            if self.buffer:
                complete_event = "\n".join(self.buffer) + "\n\n"
                self.buffer = []
                return complete_event
            return None
        self.buffer.append(line)
        return None

    def flush(self) -> Optional[str]:
        """Return any buffered lines as a final event on stream close."""
        if self.buffer:
            complete_event = "\n".join(self.buffer) + "\n\n"
            self.buffer = []
            return complete_event
        return None


def format_sse_event(data: Dict[str, Any], event_type: str | None = "message") -> bytes:
    """Serialize a JSON payload into an SSE event ready for the wire."""
    lines: list[str] = []
    if event_type:
        lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data)}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def parse_sse_json(lines: list[str]) -> Optional[Dict[str, Any]]:
    """Extract the JSON payload from a buffered group of SSE lines.

    Returns ``None`` if there is no ``data:`` line or if the concatenated
    ``data:`` lines do not form valid JSON. Callers always check for
    ``None`` because Docker Gateway occasionally sends non-JSON comments
    or partial frames.
    """
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    data_str = "\n".join(data_lines)
    try:
        return json.loads(data_str)
    except json.JSONDecodeError:
        return None
