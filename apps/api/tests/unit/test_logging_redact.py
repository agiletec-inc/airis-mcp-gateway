"""Tests for sensitive field redaction in logging (issue #105)."""
from __future__ import annotations

import json
import logging

from app.core.logging import (
    JSONFormatter,
    RedactingFormatter,
    redact_log_message,
    redact_sensitive,
)


def test_redact_sensitive_masks_known_keys():
    payload = {
        "user": "alice",
        "api_key": "sk-live-123",
        "nested": {"authorization": "Bearer xyz", "harmless": 1},
        "list": [{"password": "pw"}, {"keep": "ok"}],
    }

    result = redact_sensitive(payload)

    assert result["user"] == "alice"
    assert result["api_key"] == "***REDACTED***"
    assert result["nested"]["authorization"] == "***REDACTED***"
    assert result["nested"]["harmless"] == 1
    assert result["list"][0]["password"] == "***REDACTED***"
    assert result["list"][1]["keep"] == "ok"


def test_redact_sensitive_handles_case_insensitive_keys():
    assert redact_sensitive({"API_KEY": "x"}) == {"API_KEY": "***REDACTED***"}
    assert redact_sensitive({"Authorization": "x"}) == {"Authorization": "***REDACTED***"}


def test_redact_sensitive_returns_primitives_unchanged():
    assert redact_sensitive("plain string") == "plain string"
    assert redact_sensitive(42) == 42
    assert redact_sensitive(None) is None


def test_redact_log_message_masks_inline_literals():
    line = 'calling with "api_key": "sk-live-abc123" and ok=1'
    masked = redact_log_message(line)
    assert "sk-live-abc123" not in masked
    assert "***REDACTED***" in masked


def test_redact_log_message_masks_authorization_header_fragment():
    line = "upstream headers: authorization=Bearer xyz; content-type=application/json"
    masked = redact_log_message(line)
    assert "Bearer xyz" not in masked
    assert "***REDACTED***" in masked


def test_json_formatter_redacts_message():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg='payload={"api_key": "sk-secret"}',
        args=(),
        exc_info=None,
    )
    record.request_id = "-"
    formatter = JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S")

    emitted = json.loads(formatter.format(record))
    assert "sk-secret" not in emitted["message"]
    assert "***REDACTED***" in emitted["message"]


def test_redacting_formatter_masks_human_readable():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="password=hunter2 user=alice",
        args=(),
        exc_info=None,
    )
    record.request_id = "-"
    formatter = RedactingFormatter("%(message)s")

    emitted = formatter.format(record)
    assert "hunter2" not in emitted
    assert "alice" in emitted
