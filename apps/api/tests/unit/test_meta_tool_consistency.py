"""
Meta-tool handler <-> advertisement consistency canary (issue #196).

Two independent sources of truth must agree on the set of `airis-*` meta-tools:

1. What `DynamicMCP.get_meta_tools()` *advertises* (in "full" mode, a
   superset of "core" mode — see `get_meta_tools()`'s `tools.extend(...)`
   structure).
2. What `_proxy_jsonrpc_request()` in `mcp_proxy.py` actually *dispatches* to
   a handler, i.e. every `if tool_name == "airis-...":` branch in the
   `tools/call` routing block.

If a tool is advertised but has no handler, calling it 404s at runtime.
If a tool is handled but never advertised, it is dead code reachable only by
a client that already knows the (undocumented) name — exactly the shape of
the `airis-activate` bug this canary was written to catch (issue #196):
`handle_airis_activate` existed and was dispatched to, but `get_meta_tools()`
never advertised `airis-activate` in any mode.

This test is RED on the tree before the #196 cleanup (airis-activate handled
but not advertised) and GREEN after the dead handler is removed.
"""
import ast
from pathlib import Path

from app.core.dynamic_mcp import DynamicMCP

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "app"
MCP_PROXY_PATH = SRC_ROOT / "api" / "endpoints" / "mcp_proxy.py"


def _advertised_meta_tool_names() -> set[str]:
    """The full set of airis-* names DynamicMCP will ever advertise.

    "full" mode is documented as a superset of "core" mode (get_meta_tools
    builds the core list, then `.extend()`s the full-only tools onto it), so
    scanning "full" alone covers every mode.
    """
    mcp = DynamicMCP()
    tools = mcp.get_meta_tools(mode="full")
    names = {t["name"] for t in tools}
    assert names, "get_meta_tools(mode='full') returned nothing — sanity check failed"
    return {n for n in names if n.startswith("airis-")}


def _handled_airis_tool_names() -> set[str]:
    """AST-scan mcp_proxy.py for every `tool_name == "airis-..."` dispatch.

    Robust to refactors that move the dispatch block around inside the file:
    walks the whole module tree for `if <Name> == "airis-..."` comparisons
    rather than anchoring on a specific function or line range.
    """
    source = MCP_PROXY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MCP_PROXY_PATH))

    handled: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
            continue
        left = node.left
        (right,) = node.comparators
        # Accept either orientation: `tool_name == "airis-x"` or the reverse.
        left_is_name = isinstance(left, ast.Name) and left.id == "tool_name"
        right_is_name = isinstance(right, ast.Name) and right.id == "tool_name"
        const_node = right if left_is_name else (left if right_is_name else None)
        if const_node is None:
            continue
        if isinstance(const_node, ast.Constant) and isinstance(const_node.value, str):
            if const_node.value.startswith("airis-"):
                handled.add(const_node.value)

    assert handled, "AST scan found no `tool_name == \"airis-...\"` dispatch — extraction is broken"
    return handled


def test_dynamic_mcp_parses_as_python():
    """Sanity check the AST-scan target file is valid Python (mirrors the
    guard in test_dynamic_mcp_meta_tools.py for dynamic_mcp.py itself)."""
    source = MCP_PROXY_PATH.read_text(encoding="utf-8")
    ast.parse(source, filename=str(MCP_PROXY_PATH))


def test_every_advertised_meta_tool_has_a_handler():
    advertised = _advertised_meta_tool_names()
    handled = _handled_airis_tool_names()
    missing_handlers = advertised - handled
    assert not missing_handlers, (
        f"Advertised meta-tool(s) with no dispatch handler in mcp_proxy.py: "
        f"{sorted(missing_handlers)}"
    )


def test_every_handled_airis_tool_is_advertised_in_some_mode():
    advertised = _advertised_meta_tool_names()
    handled = _handled_airis_tool_names()
    unadvertised_handlers = handled - advertised
    assert not unadvertised_handlers, (
        f"mcp_proxy.py dispatches to airis-* tool(s) that get_meta_tools() "
        f"never advertises in any mode (dead/undiscoverable handler): "
        f"{sorted(unadvertised_handlers)}"
    )
