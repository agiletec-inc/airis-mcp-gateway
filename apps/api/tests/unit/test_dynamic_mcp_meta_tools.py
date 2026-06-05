"""
Regression tests for the DynamicMCP meta-tool definitions and Lazy Schema.

Guards:
- The meta-tools literal must remain syntactically valid (an earlier edit left
  dangling braces and an orphaned `"required": ["tool"]` after the airis-exec
  definition, making the file unparseable).
- Core mode must yield exactly two tools (airis-find, airis-schema);
  full mode must add the four optional meta-tools.
- Lazy Schema: active tool definitions must expose stub `{"type": "object"}`
  inputSchemas so the client never ingests the backend's full JSON schema.
"""
import ast
from pathlib import Path

from app.core.dynamic_mcp import DynamicMCP, ToolInfo

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
    assert names == ["airis-find", "airis-schema"]
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


def test_full_meta_tools_adds_optional_tools():
    mcp = DynamicMCP()
    tools = mcp.get_meta_tools(mode="full")
    names = {t["name"] for t in tools}
    assert {"airis-confidence", "airis-repo-index", "airis-suggest", "airis-route"} <= names


def test_deprecated_meta_tools_removed():
    """airis-exec and airis-activate are no longer exposed as meta-tools.

    They were marked [DEPRECATED] and have been removed from the core toolset.
    Their routing logic (auto-discovery, auto-enable) remains as internal handlers.
    """
    mcp = DynamicMCP()
    tools = {t["name"] for t in mcp.get_meta_tools(mode="core")}
    assert "airis-exec" not in tools, "airis-exec removed from core meta-tools"
    assert "airis-activate" not in tools, "airis-activate removed from core meta-tools"


def test_active_tool_definitions_use_lazy_schema():
    """Active tool definitions must expose stub schemas, not the backend's full schema.

    This is the core Lazy Schema invariant: clients see names only, the full
    schema is only retrieved via airis-schema or as an error payload on -32602.
    """
    mcp = DynamicMCP()
    mcp._tools["stripe:create_customer"] = ToolInfo(
        name="stripe:create_customer",
        server="stripe",
        description="Create a customer",
        input_schema={
            "type": "object",
            "properties": {"email": {"type": "string"}, "name": {"type": "string"}},
            "required": ["email"],
        },
        source="process",
    )
    mcp._active_tools.add("stripe:create_customer")

    defs = mcp.get_active_tool_definitions()
    assert len(defs) == 1
    assert defs[0]["name"] == "stripe:create_customer"
    assert defs[0]["inputSchema"] == {"type": "object"}, (
        "Active tool inputSchema must be stubbed to {'type':'object'} to keep "
        "the client context small; the full schema is served via airis-schema."
    )
