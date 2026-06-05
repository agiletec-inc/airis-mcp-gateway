"""
Unit tests for the airis-workflow meta-tool.

Covers:
- compile_to: airis_workflow content is NOT dumped into initialize instructions
  (it is served on-demand, not always-loaded).
- handle_airis_workflow returns the workflow text for a known topic, and a
  -32602 error for a missing or unknown topic.
"""
import json

import pytest

from app.api.endpoints.mcp_proxy import handle_airis_workflow
from app.core.behavior_compiler import _compile_workflow_texts
from app.core.workflow_loader import WorkflowConfig


def _wf(name, compile_to, topic="", text="body", priority="medium"):
    return WorkflowConfig(
        name=name,
        compile_to=compile_to,
        priority=priority,
        text=text,
        topic=topic,
    )


def test_airis_workflow_excluded_from_initialize_instructions():
    """Only compile_to: mcp_instructions reaches the initialize instructions."""
    workflows = [
        _wf("a-init", "mcp_instructions", text="INIT TEXT"),
        _wf("a-db", "airis_workflow", topic="database", text="ON DEMAND TEXT"),
    ]
    compiled = _compile_workflow_texts(workflows)
    assert "INIT TEXT" in compiled
    assert "ON DEMAND TEXT" not in compiled


async def _call_handler(topic):
    """Invoke handle_airis_workflow (no session) and return the parsed JSON body."""
    arguments = {} if topic is None else {"topic": topic}
    rpc_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "airis-workflow", "arguments": arguments},
    }
    response = await handle_airis_workflow(rpc_request)
    return json.loads(response.body)


_FAKE_WORKFLOWS = [
    _wf("airis-workflow-database", "airis_workflow", topic="database", text="DB PROCEDURE"),
    _wf("data-query", "mcp_instructions", topic="", text="INIT ONLY"),
]


@pytest.mark.asyncio
async def test_known_topic_returns_workflow_text(monkeypatch):
    monkeypatch.setattr(
        "app.core.workflow_loader.load_workflows",
        lambda *a, **k: list(_FAKE_WORKFLOWS),
    )
    result = await _call_handler("database")
    assert "result" in result
    assert result["result"]["content"][0]["text"] == "DB PROCEDURE"


@pytest.mark.asyncio
async def test_unknown_topic_returns_error(monkeypatch):
    monkeypatch.setattr(
        "app.core.workflow_loader.load_workflows",
        lambda *a, **k: list(_FAKE_WORKFLOWS),
    )
    result = await _call_handler("nonsense")
    assert "error" in result
    assert result["error"]["code"] == -32602
    assert "database" in result["error"]["message"]  # valid topics listed


@pytest.mark.asyncio
async def test_missing_topic_returns_error(monkeypatch):
    monkeypatch.setattr(
        "app.core.workflow_loader.load_workflows",
        lambda *a, **k: list(_FAKE_WORKFLOWS),
    )
    result = await _call_handler(None)
    assert "error" in result
    assert result["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_mcp_instructions_workflow_not_served_as_topic(monkeypatch):
    """A compile_to: mcp_instructions workflow is not reachable via airis-workflow."""
    monkeypatch.setattr(
        "app.core.workflow_loader.load_workflows",
        lambda *a, **k: list(_FAKE_WORKFLOWS),
    )
    # data-query is mcp_instructions, not airis_workflow → not a valid topic
    result = await _call_handler("data-query")
    assert "error" in result
    assert result["error"]["code"] == -32602
