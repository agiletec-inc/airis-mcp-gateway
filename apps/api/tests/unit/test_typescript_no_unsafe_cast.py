"""
Regression test for issue #106: TypeScript args use `as unknown as T`
bypassing runtime validation.

07dd06ce replaced every `as unknown as T` cast on incoming MCP tool arguments
with zod validation in both TypeScript apps. If someone drops zod and goes
back to unchecked casts, malformed tool-call payloads will crash the server
with unhelpful undefined-access errors at runtime.

This Python test is a cross-cutting guard over the two TypeScript apps.
Running vitest from unit tests is not practical (different runtime, not
available in the api container), so we:
1. Assert `as unknown as` does NOT appear in src/index.ts for either app.
2. Assert `zod` is imported in src/index.ts for either app.
3. Assert `parseArgs(` (or an equivalent zod `.safeParse`/`.parse`) is used.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

TS_APPS = [
    REPO_ROOT / "apps" / "airis-commands" / "src" / "index.ts",
    REPO_ROOT / "apps" / "gateway-control" / "src" / "index.ts",
]

# Inside the api container only apps/api is COPYed, so the TS sources are
# unreachable. CI checks out the full repo, where these paths resolve; that
# is the authoritative gate.
if not all(p.exists() for p in TS_APPS):
    pytest.skip(
        "TypeScript app sources not reachable — likely running inside the "
        "api container, skipping. CI on a full repo checkout provides the "
        "real gate.",
        allow_module_level=True,
    )


@pytest.mark.parametrize("ts_file", TS_APPS, ids=lambda p: p.parent.parent.name)
def test_ts_app_exists(ts_file: Path):
    assert ts_file.is_file(), f"{ts_file} missing"


@pytest.mark.parametrize("ts_file", TS_APPS, ids=lambda p: p.parent.parent.name)
def test_ts_app_has_no_unsafe_cast(ts_file: Path):
    """`as unknown as T` is the specific anti-pattern #106 called out.

    We check for the substring `as unknown as` rather than a regex because
    that is the exact form the commit removed, and any legitimate variant
    should be challenged in code review.
    """
    content = ts_file.read_text(encoding="utf-8")
    # Strip single-line comments before matching so a "// avoid `as unknown as`"
    # note in the source doesn't trigger us.
    stripped = re.sub(r"//[^\n]*", "", content)
    assert "as unknown as" not in stripped, (
        f"{ts_file.relative_to(REPO_ROOT)} contains `as unknown as` which "
        "bypasses runtime validation (issue #106). Use zod instead."
    )


@pytest.mark.parametrize("ts_file", TS_APPS, ids=lambda p: p.parent.parent.name)
def test_ts_app_imports_zod(ts_file: Path):
    content = ts_file.read_text(encoding="utf-8")
    # Accept both `import { z } from "zod"` and `import * as z from "zod"`.
    assert re.search(r'from\s+["\']zod["\']', content), (
        f"{ts_file.relative_to(REPO_ROOT)} does not import zod. MCP tool "
        "arguments must be runtime-validated with zod (issue #106)."
    )


@pytest.mark.parametrize("ts_file", TS_APPS, ids=lambda p: p.parent.parent.name)
def test_ts_app_actually_validates_arguments(ts_file: Path):
    """Importing zod is not enough — it has to be called on incoming args.

    Accept any of these zod validation shapes as evidence:
    - `parseArgs(` (the shared helper added in 07dd06ce)
    - `.safeParse(`
    - `.parse(`
    """
    content = ts_file.read_text(encoding="utf-8")
    has_validation = any(
        marker in content
        for marker in ("parseArgs(", ".safeParse(", ".parse(")
    )
    assert has_validation, (
        f"{ts_file.relative_to(REPO_ROOT)} imports zod but never calls "
        "parseArgs/.safeParse/.parse on tool arguments (issue #106)."
    )
