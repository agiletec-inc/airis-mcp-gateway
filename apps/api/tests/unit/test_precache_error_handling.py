"""
Regression tests for issues #103 and #108 in the Docker Gateway precache
startup path (apps/api/src/app/main.py).

#103: swallowed json.JSONDecodeError hides Docker Gateway startup failures.
    The precache loop must log the error (at WARNING or higher) instead of
    silently continuing.

#108: startup precache uses hardcoded sleeps instead of readiness polling.
    The precache must call `_wait_for_docker_gateway()` (an exponential-
    backoff /health poll) before issuing MCP requests, not `asyncio.sleep(2)`.

Both checks are static — we cannot spin up a real Docker Gateway in unit
tests — but they are expressed over the parsed AST of main.py, so any future
edit that reintroduces the bugs will fail at CI time.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "app"
MAIN_PY = SRC_ROOT / "main.py"


def _load_main_ast() -> ast.Module:
    assert MAIN_PY.is_file(), f"{MAIN_PY} not found"
    return ast.parse(MAIN_PY.read_text(encoding="utf-8"), filename=str(MAIN_PY))


def _find_function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    pytest.fail(f"function {name!r} not found in {MAIN_PY}")


# ---------------------------------------------------------------------------
# #108 — exponential-backoff /health poll instead of hardcoded sleep
# ---------------------------------------------------------------------------


def test_wait_for_docker_gateway_function_exists():
    """#108: the exponential-backoff helper must be defined."""
    tree = _load_main_ast()
    fn = _find_function(tree, "_wait_for_docker_gateway")
    assert isinstance(fn, ast.AsyncFunctionDef), (
        "_wait_for_docker_gateway must be async"
    )


def test_precache_awaits_health_poll_not_hardcoded_sleep():
    """#108: _precache_docker_gateway_tools must call _wait_for_docker_gateway
    before any MCP traffic, and must not `await asyncio.sleep(<big literal>)`
    as its gating step.
    """
    tree = _load_main_ast()
    precache = _find_function(tree, "_precache_docker_gateway_tools")

    # Must contain at least one call to _wait_for_docker_gateway.
    health_poll_calls = [
        node
        for node in ast.walk(precache)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_wait_for_docker_gateway"
    ]
    assert health_poll_calls, (
        "_precache_docker_gateway_tools no longer calls "
        "_wait_for_docker_gateway() — the old hardcoded sleep regression "
        "has returned (issue #108)."
    )

    # Must NOT contain asyncio.sleep(N) where N >= 1 at the top of the
    # function (i.e. before the first gateway call). We allow small delays
    # inside the inner sender task (asyncio.sleep(0.3) for stream handshake)
    # because those are part of the MCP protocol, not the outer gate.
    #
    # Strategy: inspect only statements that are direct children of the
    # function body, before the first `async with` block (the body of which
    # is the request loop). Any await asyncio.sleep(>=1) there is the bug.
    for stmt in precache.body:
        if isinstance(stmt, ast.AsyncWith):
            # Reached the request loop — stop scanning.
            break
        for node in ast.walk(stmt):
            if not (isinstance(node, ast.Await) and isinstance(node.value, ast.Call)):
                continue
            call = node.value
            if not (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "sleep"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "asyncio"
            ):
                continue
            if call.args and isinstance(call.args[0], ast.Constant):
                value = call.args[0].value
                if isinstance(value, (int, float)) and value >= 1:
                    pytest.fail(
                        f"_precache_docker_gateway_tools awaits "
                        f"asyncio.sleep({value}) as a gating step before the "
                        "MCP request loop. Replace it with "
                        "_wait_for_docker_gateway() (issue #108)."
                    )


# ---------------------------------------------------------------------------
# #103 — surface JSONDecodeError instead of silently swallowing
# ---------------------------------------------------------------------------


def test_precache_logs_jsondecodeerror_instead_of_swallowing():
    """#103: the except json.JSONDecodeError handler inside the precache loop
    must call logger.warning (or logger.error / logger.exception) — i.e. it
    must not be a bare ``except ...: continue`` anymore.
    """
    tree = _load_main_ast()
    precache = _find_function(tree, "_precache_docker_gateway_tools")

    handlers = [
        node
        for node in ast.walk(precache)
        if isinstance(node, ast.ExceptHandler)
    ]

    json_handlers = []
    for handler in handlers:
        exc_type = handler.type
        # Match `except json.JSONDecodeError` and `except JSONDecodeError`.
        is_match = False
        if isinstance(exc_type, ast.Attribute) and exc_type.attr == "JSONDecodeError":
            is_match = True
        elif isinstance(exc_type, ast.Name) and exc_type.id == "JSONDecodeError":
            is_match = True
        if is_match:
            json_handlers.append(handler)

    assert json_handlers, (
        "_precache_docker_gateway_tools no longer has an `except "
        "json.JSONDecodeError` handler in its parsing loop. Either the loop "
        "was removed or the exception is now caught too broadly — either "
        "way #103 needs re-review."
    )

    for handler in json_handlers:
        logs = [
            node
            for node in ast.walk(handler)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"warning", "error", "exception", "info"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ]
        assert logs, (
            "except json.JSONDecodeError handler in _precache_docker_gateway_tools "
            "silently swallows the error (no logger call). Log it so stuck "
            "precache is diagnosable (issue #103)."
        )
