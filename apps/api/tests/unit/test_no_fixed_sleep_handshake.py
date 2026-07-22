"""
Gate for issue #194: the MCP initialize->initialized handshake and the
Docker Gateway pre-cache startup sequence must not rely on fixed wall-clock
sleeps to paper over races (e.g. "wait 0.15s for the Gateway to process the
request"). Those budgets are exactly what breaks under load.

This test AST-parses the specific handshake/startup functions and fails if
any bare `asyncio.sleep(<numeric literal>)` remains in them, with two
narrow exceptions:

* `asyncio.sleep(0)` — a pure event-loop yield, not a race-driven wait.
* A sleep whose surrounding comment block contains the literal string
  "no-observable-event" — a documented last resort for a step that
  genuinely has no observable completion signal (e.g. a JSON-RPC
  *notification*, which by protocol has no response to wait on). See
  .github/ISSUE_TEMPLATE/mcp-init-race.md for the upstream limitation this
  documents.

Any other fixed sleep in these functions must be replaced with an explicit
await on the real condition (a queued response, an asyncio.Event, etc.)
bounded by asyncio.wait_for(..., timeout=...).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# (file relative to apps/api/src/app, [function names to inspect])
TARGETS: dict[str, list[str]] = {
    "src/app/api/endpoints/mcp_proxy.py": ["_proxy_jsonrpc_request"],
    "src/app/main.py": ["_precache_docker_gateway_tools"],
}

NO_OBSERVABLE_EVENT_MARKER = "no-observable-event"


def _find_named_functions(
    tree: ast.Module, names: set[str]
) -> list[ast.AsyncFunctionDef]:
    """Find top-level (or nested) function defs matching the given names."""
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        ):
            found.append(node)
    return found


def _is_asyncio_sleep_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    # asyncio.sleep(...)
    if isinstance(func, ast.Attribute) and func.attr == "sleep":
        if isinstance(func.value, ast.Name) and func.value.id == "asyncio":
            return True
    return False


def _numeric_literal(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    return None


def _has_marker_nearby(
    lines: list[str], lineno: int, marker: str, lookback: int = 12
) -> bool:
    """Check the call's own line and up to `lookback` preceding lines for marker."""
    start = max(0, lineno - 1 - lookback)
    end = lineno  # lineno is 1-indexed; lines[lineno-1] is the call's own line
    window = "\n".join(lines[start:end])
    return marker in window


def _violations_in_function(
    fn: ast.AsyncFunctionDef | ast.FunctionDef, lines: list[str]
) -> list[str]:
    violations = []
    for node in ast.walk(fn):
        if not _is_asyncio_sleep_call(node):
            continue
        if not node.args:
            continue
        value = _numeric_literal(node.args[0])
        if value is None:
            # Not a numeric literal (e.g. a variable/backoff expression) —
            # out of scope for this gate.
            continue
        if value == 0:
            continue
        if _has_marker_nearby(lines, node.lineno, NO_OBSERVABLE_EVENT_MARKER):
            continue
        violations.append(
            f"{fn.name}() line {node.lineno}: asyncio.sleep({value!r}) is a fixed "
            "wall-clock wait with no documented no-observable-event justification"
        )
    return violations


def test_handshake_and_startup_functions_have_no_fixed_sleeps():
    all_violations: list[str] = []

    for rel_path, fn_names in TARGETS.items():
        abs_path = REPO_ROOT / rel_path
        source = abs_path.read_text()
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(abs_path))

        matched = _find_named_functions(tree, set(fn_names))
        found_names = {fn.name for fn in matched}
        missing = set(fn_names) - found_names
        assert not missing, f"{rel_path}: expected function(s) not found: {missing}"

        for fn in matched:
            all_violations.extend(
                f"{rel_path}: {v}" for v in _violations_in_function(fn, lines)
            )

    assert not all_violations, "Fixed-sleep handshake races found:\n" + "\n".join(
        all_violations
    )
