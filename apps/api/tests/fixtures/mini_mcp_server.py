#!/usr/bin/env python3
"""
Minimal stdio MCP server used by tests/unit/test_cold_server_startup.py to
exercise the real COLD-server startup path (spawn -> initialize handshake ->
tools/list -> tools/call) without depending on any real, external MCP
server binary.

Speaks newline-delimited JSON-RPC 2.0 on stdin/stdout, matching exactly the
subset ProcessRunner (src/app/core/process_runner.py) requires:
  - `initialize`            -> result with serverInfo/capabilities
  - `notifications/initialized` (notification, no response)
  - `tools/list`             -> one "echo" tool
  - `tools/call` name="echo" -> echoes back the given arguments as text

No fixed sleeps — reads and responds to each request as it arrives, so the
real event-driven handshake in ProcessRunner (issue #194 / PR #202) is
exercised for real, not simulated.
"""

from __future__ import annotations

import json
import sys


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method")
        request_id = request.get("id")

        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mini-mcp-server", "version": "0.1.0"},
                    },
                }
            )

        elif method == "notifications/initialized":
            # Notification — no response expected.
            continue

        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echo back the given message argument",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"message": {"type": "string"}},
                                    "required": ["message"],
                                },
                            }
                        ]
                    },
                }
            )

        elif method == "tools/call":
            params = request.get("params", {})
            arguments = params.get("arguments", {})
            if params.get("name") == "echo":
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"echo: {arguments.get('message', '')}",
                                }
                            ],
                            "isError": False,
                        },
                    }
                )
            else:
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Unknown tool: {params.get('name')}",
                        },
                    }
                )

        elif request_id is not None:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )


if __name__ == "__main__":
    main()
