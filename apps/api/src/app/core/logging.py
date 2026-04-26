"""
Logging configuration for AIRIS MCP Gateway.

Provides structured logging with configurable levels and formats.
Supports request_id context for request tracing.
"""
import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from typing import Any, Optional


# Context variable for request ID - set by logging_context middleware
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


# Keys whose values should never appear in logs.
_SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "auth_token",
    "bearer",
    "password",
    "passwd",
    "secret",
    "private_key",
    "client_secret",
    "session_token",
    "cookie",
)

_REDACTED = "***REDACTED***"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def redact_sensitive(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact sensitive fields in a dict/list/JSON structure.

    Safe to call on arbitrary objects - unknown types are returned as-is.
    Depth is capped to avoid runaway recursion on cyclic structures.
    """
    if _depth > 8:
        return "***TRUNCATED***"

    if isinstance(value, dict):
        return {
            k: (_REDACTED if _is_sensitive_key(str(k)) else redact_sensitive(v, _depth=_depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        redacted_items = [redact_sensitive(item, _depth=_depth + 1) for item in value]
        return type(value)(redacted_items) if isinstance(value, tuple) else redacted_items
    return value


# Matches `"api_key": "xxx"` / `'token': 'yyy'` / `authorization=zzz` style fragments
# inside an already-stringified log message, as a safety net when callers bypass
# the explicit redact_sensitive() helper.
_STRING_REDACTION_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(rf'(?i)(["\']?{fragment}["\']?\s*[:=]\s*)(["\'][^"\']*["\']|\S+)')
    for fragment in _SENSITIVE_KEY_FRAGMENTS
)


def redact_log_message(message: str) -> str:
    """Post-process a formatted log message to mask obvious secret literals."""
    result = message
    for pattern in _STRING_REDACTION_PATTERNS:
        result = pattern.sub(lambda m: f"{m.group(1)}{_REDACTED}", result)
    return result


class RequestIDFilter(logging.Filter):
    """
    Filter that adds request_id to log records.

    Reads from ContextVar set by logging_context middleware.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Output format:
    {"timestamp": "...", "level": "...", "logger": "...", "request_id": "...", "message": "..."}
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": redact_log_message(record.getMessage()),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = redact_log_message(self.formatException(record.exc_info))

        return json.dumps(log_data, ensure_ascii=False)


class RedactingFormatter(logging.Formatter):
    """Human-readable formatter that also masks sensitive literals."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_message(super().format(record))


def setup_logging(
    level: Optional[str] = None,
    format_style: Optional[str] = None
) -> None:
    """
    Configure application-wide logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
               Defaults to LOG_LEVEL env var or INFO.
        format_style: "standard" for human-readable, "json" for structured logging.
                      Defaults to LOG_FORMAT env var or "json" (production default).
    """
    log_level = level or os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = format_style or os.getenv("LOG_FORMAT", "json").lower()

    # Validate log level
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)

    # Add request ID filter
    handler.addFilter(RequestIDFilter())

    # Configure formatter based on format style
    if log_format == "json":
        handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
    else:
        # Human-readable format for development (also redacts secrets)
        handler.setFormatter(RedactingFormatter(
            "[%(asctime)s] %(levelname)s %(name)s [%(request_id)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))

    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


def set_request_id(request_id: Optional[str]) -> None:
    """
    Set the request ID for the current context.

    Called by logging_context middleware at the start of each request.

    Args:
        request_id: The request ID to set
    """
    request_id_var.set(request_id)


def get_request_id() -> Optional[str]:
    """
    Get the request ID from the current context.

    Returns:
        The current request ID, or None if not set
    """
    return request_id_var.get()


# Module-level loggers for convenience
# Usage: from app.core.logging import logger
logger = get_logger("airis")
