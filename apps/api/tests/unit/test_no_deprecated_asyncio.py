"""
Regression test for issue #98: deprecated asyncio.get_event_loop() usage.

Python 3.10+ emits DeprecationWarning when asyncio.get_event_loop() is called
without a running loop, and Python 3.12+ will raise. Inside coroutines we must
use asyncio.get_running_loop() instead.

This test statically scans the source tree with the `ast` module and fails if
any `asyncio.get_event_loop()` call reappears. It is intentionally a static
check (not a runtime check) because #98 is a code-style invariant: the fix is
"do not write this call", not "handle it at runtime".
"""
import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "app"


def _iter_python_files(root: Path):
    yield from root.rglob("*.py")


def _find_get_event_loop_calls(tree: ast.AST) -> list[tuple[int, int]]:
    """Return (lineno, col_offset) for every `asyncio.get_event_loop()` call."""
    hits: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get_event_loop"
            and isinstance(func.value, ast.Name)
            and func.value.id == "asyncio"
        ):
            hits.append((node.lineno, node.col_offset))
    return hits


def test_src_root_exists():
    assert SRC_ROOT.is_dir(), f"expected source dir at {SRC_ROOT}"


def test_no_deprecated_get_event_loop_in_source():
    """Regression guard for issue #98.

    Scans apps/api/src/app/ recursively and fails if any file contains a
    literal `asyncio.get_event_loop()` call. Use `asyncio.get_running_loop()`
    inside coroutines instead.
    """
    offenders: list[str] = []
    repo_root = SRC_ROOT.parents[2]
    for path in _iter_python_files(SRC_ROOT):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            pytest.fail(f"failed to parse {path}: {exc}")
        hits = _find_get_event_loop_calls(tree)
        for lineno, col in hits:
            offenders.append(f"{path.relative_to(repo_root)}:{lineno}:{col}")

    assert not offenders, (
        "asyncio.get_event_loop() is deprecated in Python 3.10+ and will be "
        "removed. Use asyncio.get_running_loop() inside coroutines. "
        "Offending locations:\n  " + "\n  ".join(offenders)
    )


def test_regression_detector_itself_works(tmp_path: Path):
    """Meta-test: make sure the AST matcher actually catches the bad pattern.

    Without this, the real test could silently pass because the matcher is
    broken rather than because the source is clean.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import asyncio\n"
        "async def f():\n"
        "    loop = asyncio.get_event_loop()\n"
        "    return loop\n",
        encoding="utf-8",
    )
    tree = ast.parse(sample.read_text(encoding="utf-8"))
    hits = _find_get_event_loop_calls(tree)
    assert len(hits) == 1, f"matcher failed to find the bad call, hits={hits}"
