"""
Regression tests for the DynamicMCP meta-tool definitions and Lazy Schema.

Guards:
- The meta-tools literal must remain syntactically valid (an earlier edit left
  dangling braces and an orphaned `"required": ["tool"]` after the airis-exec
  definition, making the file unparseable).
- Core mode must yield four tools (airis-find, airis-schema, airis-workflow,
  airis-exec); full mode must add the four optional meta-tools.
"""
import ast
from pathlib import Path

from app.core.dynamic_mcp import DynamicMCP

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "app"
DYNAMIC_MCP_PATH = SRC_ROOT / "core" / "dynamic_mcp.py"


def test_dynamic_mcp_parses_as_python():
    """The file must be valid Python source."""
    source = DYNAMIC_MCP_PATH.read_text(encoding="utf-8")
    ast.parse(source, filename=str(DYNAMIC_MCP_PATH))


def test_core_meta_tools_shape():
    mcp = DynamicMCP()
    tools = mcp.get_meta_tools(mode="core")
    names = [t["name"] for t in tools]
    assert names == ["airis-find", "airis-schema", "airis-workflow", "airis-exec"]
    for tool in tools:
        assert "inputSchema" in tool
        assert tool["inputSchema"].get("type") == "object"


def test_airis_find_advertises_inventory_and_server_drilldown():
    """airis-find must expose the `server` param and document the bare-call
    inventory so clients can discover servers/tools without guessing."""
    mcp = DynamicMCP()
    find = next(t for t in mcp.get_meta_tools(mode="core") if t["name"] == "airis-find")
    props = find["inputSchema"]["properties"]
    assert "query" in props
    assert "server" in props  # was supported by the handler but hidden from the schema
    desc = find["description"].lower()
    assert "no argument" in desc  # bare call → full inventory
    assert "server" in desc


def test_airis_workflow_is_core_tool_with_topic_enum():
    """airis-workflow is a core meta-tool taking a required topic enum."""
    mcp = DynamicMCP()
    core = {t["name"]: t for t in mcp.get_meta_tools(mode="core")}
    assert "airis-workflow" in core
    schema = core["airis-workflow"]["inputSchema"]
    assert schema["required"] == ["topic"]
    assert set(schema["properties"]["topic"]["enum"]) == {
        "database",
        "debugging",
        "implementation",
        "research",
    }


def test_full_meta_tools_adds_optional_tools():
    mcp = DynamicMCP()
    tools = mcp.get_meta_tools(mode="full")
    names = {t["name"] for t in tools}
    assert {"airis-confidence", "airis-repo-index", "airis-suggest", "airis-route"} <= names


def test_airis_exec_is_core_router():
    """airis-exec is a core meta-tool: the always-advertised router that lets
    tools/list-only clients (Claude Code, Codex) reach COLD-server tools, which
    are otherwise absent from tools/list. Its handler (handle_airis_exec) auto-
    discovers and auto-enables the COLD server on first call.

    airis-activate stays out — airis-exec alone covers COLD reachability.
    """
    mcp = DynamicMCP()
    core = {t["name"]: t for t in mcp.get_meta_tools(mode="core")}
    assert "airis-exec" in core, "airis-exec must be advertised so clients can call COLD tools"
    assert core["airis-exec"]["inputSchema"]["required"] == ["tool"]
    assert "airis-activate" not in core, "airis-activate is not re-exposed (airis-exec suffices)"
