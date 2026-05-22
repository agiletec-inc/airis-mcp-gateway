"""Tests for ProtocolLogger (issue #85).

ProtocolLogger appends MCP protocol messages to a JSONL file. These tests
cover directory resolution (including the /tmp fallback), the entry shape
written by log_message, the request/response helper methods, and log
clearing.
"""
from __future__ import annotations

import json

import pytest

from app.core.protocol_logger import ProtocolLogger


@pytest.fixture(autouse=True)
def _no_protocol_log_dir_env(monkeypatch):
    """Ensure a stray PROTOCOL_LOG_DIR in the environment never leaks into tests."""
    monkeypatch.delenv("PROTOCOL_LOG_DIR", raising=False)


def _read_entries(logger: ProtocolLogger) -> list[dict]:
    """Parse the logger's JSONL file into a list of entries."""
    return [
        json.loads(line)
        for line in logger.log_file.read_text().splitlines()
        if line.strip()
    ]


def test_init_creates_log_dir(tmp_path):
    target = tmp_path / "logs"

    logger = ProtocolLogger(log_dir=target)

    assert logger.log_dir == target
    assert target.is_dir()
    assert logger.log_file == target / "protocol_messages.jsonl"


def test_init_respects_protocol_log_dir_env(tmp_path, monkeypatch):
    env_dir = tmp_path / "from_env"
    monkeypatch.setenv("PROTOCOL_LOG_DIR", str(env_dir))

    # The env var overrides the constructor argument.
    logger = ProtocolLogger(log_dir=tmp_path / "ignored")

    assert logger.log_dir == env_dir
    assert env_dir.is_dir()


def test_ensure_log_dir_falls_back_when_uncreatable(tmp_path):
    # A regular file cannot host a child directory — mkdir raises OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    unusable = blocker / "logs"

    logger = ProtocolLogger(log_dir=unusable)

    assert logger.log_dir != unusable
    assert logger.log_dir.is_dir()


@pytest.mark.asyncio
async def test_log_message_writes_jsonl_entry(tmp_path):
    logger = ProtocolLogger(log_dir=tmp_path)

    await logger.log_message(
        "client→server",
        {"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
    )

    entries = _read_entries(logger)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["direction"] == "client→server"
    assert entry["method"] == "tools/list"
    assert entry["id"] == 7
    assert entry["has_result"] is False
    assert entry["has_error"] is False
    assert "metadata" not in entry
    assert "timestamp" in entry


@pytest.mark.asyncio
async def test_log_message_includes_metadata_and_result_flags(tmp_path):
    logger = ProtocolLogger(log_dir=tmp_path)

    await logger.log_message(
        "server→client",
        {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}},
        metadata={"server": "context7"},
    )

    entry = _read_entries(logger)[0]
    assert entry["has_result"] is True
    assert entry["has_error"] is False
    assert entry["metadata"] == {"server": "context7"}


@pytest.mark.asyncio
async def test_log_message_appends_successive_entries(tmp_path):
    logger = ProtocolLogger(log_dir=tmp_path)

    await logger.log_message("client→server", {"id": 1})
    await logger.log_message("client→server", {"id": 2})

    assert [e["id"] for e in _read_entries(logger)] == [1, 2]


@pytest.mark.asyncio
async def test_log_initialize_writes_request_and_response(tmp_path):
    logger = ProtocolLogger(log_dir=tmp_path)

    await logger.log_initialize(
        {"id": 1, "method": "initialize"},
        {"id": 1, "result": {}},
    )

    entries = _read_entries(logger)
    assert [e["direction"] for e in entries] == ["client→server", "server→client"]
    assert all(e["metadata"]["phase"] == "initialize" for e in entries)


@pytest.mark.asyncio
async def test_log_tools_list_records_pattern(tmp_path):
    logger = ProtocolLogger(log_dir=tmp_path)

    await logger.log_tools_list({"id": 1}, {"id": 1, "result": {}}, pattern="openmcp")

    entries = _read_entries(logger)
    assert len(entries) == 2
    assert all(e["metadata"]["phase"] == "tools_list" for e in entries)
    assert all(e["metadata"]["pattern"] == "openmcp" for e in entries)


@pytest.mark.asyncio
async def test_log_tools_call_records_tool_name_and_call_number(tmp_path):
    logger = ProtocolLogger(log_dir=tmp_path)

    await logger.log_tools_call(
        {"id": 1},
        {"id": 1, "result": {}},
        tool_name="airis-find",
        call_number=3,
    )

    entries = _read_entries(logger)
    assert len(entries) == 2
    assert all(e["metadata"]["tool_name"] == "airis-find" for e in entries)
    assert all(e["metadata"]["call_number"] == 3 for e in entries)


@pytest.mark.asyncio
async def test_clear_logs_removes_existing_file(tmp_path):
    logger = ProtocolLogger(log_dir=tmp_path)
    await logger.log_message("client→server", {"id": 1})
    assert logger.log_file.exists()

    logger.clear_logs()

    assert not logger.log_file.exists()


def test_clear_logs_is_noop_when_file_absent(tmp_path):
    logger = ProtocolLogger(log_dir=tmp_path)

    # Should not raise even though no log file has been written yet.
    logger.clear_logs()

    assert not logger.log_file.exists()
