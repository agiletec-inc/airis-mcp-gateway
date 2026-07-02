"""
AST guard: forbid the "skip when guarded file is missing" anti-pattern in
tests/unit/ (issue #195).

A guard test that does:
    if not <guarded_artifact>.exists():
        pytest.skip(...)
silently downgrades a real regression (the guarded file was deleted or
moved) into a green skip instead of a failure — exactly the "silent green"
this issue exists to eliminate.

The one legitimate shape is checking an *environment* signal that is
independent of the artifact under test: this repo's convention is `.git`
absence, meaning "not a full checkout" (e.g. `docker compose exec api
pytest tests/ -v`, where only apps/api/src is COPYed into the image, so
repo-root paths like the Dockerfile or .dockerignore never resolve). See
tests/unit/test_uv_lock_tracked.py, test_dockerignore_regression.py,
test_dockerfile_cache_mounts.py, test_package_manager_consistency.py, and
test_typescript_no_unsafe_cast.py for the sanctioned pattern.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

UNIT_DIR = Path(__file__).resolve().parent
THIS_FILE = Path(__file__).resolve()

# Substrings that, if present in the unparsed `.exists()`-checked expression,
# mark the skip as a legitimate environment-signal check rather than a
# guarded-artifact check.
ALLOWED_SIGNAL_MARKERS = (".git",)


def _is_exists_check(node: ast.expr) -> bool:
    """`X.exists()`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exists"
    )


def _is_all_exists_check(node: ast.expr) -> bool:
    """`all(p.exists() for p in XS)`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "all"
    )


def _contains_skip_call(body: list[ast.stmt]) -> bool:
    for stmt in body:
        for n in ast.walk(stmt):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "skip"
            ):
                return True
    return False


def _iter_exists_skip_guards(tree: ast.Module):
    """Yield (lineno, condition_source) for every `if not <exists check>:
    ... pytest.skip(...)` node found anywhere in the module."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
            continue
        operand = test.operand
        if not (_is_exists_check(operand) or _is_all_exists_check(operand)):
            continue
        if not _contains_skip_call(node.body):
            continue
        yield node.lineno, ast.unparse(test)


def _unit_test_files() -> list[Path]:
    return sorted(p for p in UNIT_DIR.glob("*.py") if p.resolve() != THIS_FILE)


@pytest.mark.parametrize("path", _unit_test_files(), ids=lambda p: p.name)
def test_no_file_not_found_skip_guards(path: Path):
    """Every `if not X.exists(): pytest.skip(...)` in tests/unit/ must check
    an environment signal (e.g. `.git` absence), never the guarded
    artifact's own existence — otherwise a real regression (the file was
    deleted/moved) silently skips the guard instead of failing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    for lineno, condition_src in _iter_exists_skip_guards(tree):
        assert any(marker in condition_src for marker in ALLOWED_SIGNAL_MARKERS), (
            f"{path.name}:{lineno} skips on `{condition_src}` — this checks "
            "the guarded artifact's own existence, so deleting/moving it "
            "would silently skip the guard instead of failing it. Use an "
            "environment signal (e.g. `.git` absence, matching the pattern "
            "in test_uv_lock_tracked.py) instead, and let the individual "
            "test functions assert the artifact exists (issue #195)."
        )


def test_guard_actually_detects_the_forbidden_pattern():
    """Meta-test: prove the AST scan fires on the exact anti-pattern it
    exists to forbid, so a broken detector can't silently pass everything."""
    src = (
        "from pathlib import Path\n"
        "import pytest\n"
        "TARGET = Path('/nonexistent/guarded-file.txt')\n"
        "if not TARGET.exists():\n"
        "    pytest.skip('missing', allow_module_level=True)\n"
    )
    tree = ast.parse(src, filename="<forbidden-pattern-fixture>")
    matches = list(_iter_exists_skip_guards(tree))
    assert matches, "detector failed to find the forbidden exists()-skip pattern"
    assert not any(
        any(marker in cond for marker in ALLOWED_SIGNAL_MARKERS)
        for _, cond in matches
    ), "fixture condition unexpectedly matched the allowlist"
