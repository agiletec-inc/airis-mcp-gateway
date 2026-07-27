"""
Protocol Logger for MCP Message Capture

Records all MCP protocol messages for token measurement and analysis.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import json
import os
import tempfile


class ProtocolLogger:
    """
    MCP Protocol Message Logger

    Captures all MCP protocol messages (client→server, server→client)
    for token measurement analysis.
    """

    def __init__(self, log_dir: Path = Path("logs")):
        """
        Initialize ProtocolLogger

        Args:
            log_dir: Directory for log files
        """
        requested_dir = Path(os.environ.get("PROTOCOL_LOG_DIR", str(log_dir)))
        self.log_dir = self._ensure_log_dir(requested_dir)
        self.log_file = self.log_dir / "protocol_messages.jsonl"

    async def log_message(
        self,
        direction: str,
        message: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log MCP protocol message

        Args:
            direction: "client→server" | "server→client"
            message: MCP protocol message (JSON-RPC 2.0)
            metadata: Optional metadata (server name, pattern, etc.)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "direction": direction,
            "method": message.get("method"),
            "id": message.get("id"),
            "has_result": "result" in message,
            "has_error": "error" in message,
            "message": message,
        }

        if metadata:
            log_entry["metadata"] = metadata

        # Append to JSONL file
        with self.log_file.open("a") as f:
            f.write(json.dumps(log_entry) + "\n")

    async def log_initialize(
        self, request: Dict[str, Any], response: Dict[str, Any]
    ) -> None:
        """
        Log initialize request/response pair

        Args:
            request: initialize request
            response: initialize response
        """
        await self.log_message("client→server", request, {"phase": "initialize"})
        await self.log_message("server→client", response, {"phase": "initialize"})

    async def log_tools_list(
        self,
        request: Dict[str, Any],
        response: Dict[str, Any],
        pattern: str = "unknown",
    ) -> None:
        """
        Log tools/list request/response pair

        Args:
            request: tools/list request
            response: tools/list response
            pattern: "baseline" | "openmcp" | "multi-hop"
        """
        metadata = {"phase": "tools_list", "pattern": pattern}

        await self.log_message("client→server", request, metadata)
        await self.log_message("server→client", response, metadata)

    async def log_tools_call(
        self,
        request: Dict[str, Any],
        response: Dict[str, Any],
        tool_name: str,
        call_number: int = 1,
    ) -> None:
        """
        Log tools/call request/response pair

        Args:
            request: tools/call request
            response: tools/call response
            tool_name: Name of called tool
            call_number: Call sequence number (for multi-hop analysis)
        """
        metadata = {
            "phase": "tools_call",
            "tool_name": tool_name,
            "call_number": call_number,
        }

        await self.log_message("client→server", request, metadata)
        await self.log_message("server→client", response, metadata)

    def clear_logs(self) -> None:
        """
        Clear existing log file
        """
        if self.log_file.exists():
            self.log_file.unlink()

    def _ensure_log_dir(self, candidate: Path) -> Path:
        """
        Attempt to create the requested log directory and fall back to /tmp if needed.
        """
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            fallback = Path(tempfile.gettempdir()) / "protocol_logs"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback


# Global singleton instance
protocol_logger = ProtocolLogger()
