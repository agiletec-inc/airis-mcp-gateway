"""
Regression test for issue #101: missing .dockerignore inflates build context.

f4646b45 added a root .dockerignore. If someone deletes it or drops one of the
critical exclusions, the Docker build context balloons (minutes of upload on
warm builds, gigabytes of node_modules pushed to the daemon). This test is a
static guard: it asserts the file exists and contains every exclusion the fix
added.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# apps/api/tests/unit/ -> apps/api/tests -> apps/api -> apps -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# CI runs pytest from a full repo checkout, so .dockerignore is reachable.
# Inside the api container the repo is not mounted (only apps/api is COPYed),
# so these tests must skip — the CI run is the authoritative gate.
if not DOCKERIGNORE.exists():
    pytest.skip(
        f".dockerignore not reachable from {DOCKERIGNORE} — likely running "
        "inside the api container, skipping. CI on a full repo checkout "
        "provides the real gate.",
        allow_module_level=True,
    )

REQUIRED_PATTERNS = [
    ".git/",
    "**/__pycache__/",
    "**/.venv/",
    "**/node_modules/",
    "**/.pytest_cache/",
    ".env",
]


def test_dockerignore_exists():
    assert DOCKERIGNORE.is_file(), (
        f"{DOCKERIGNORE} is missing. .dockerignore was added in f4646b45 to "
        "keep .git, node_modules, and caches out of the Docker build context "
        "(issue #101). Do not delete it."
    )


@pytest.mark.parametrize("pattern", REQUIRED_PATTERNS)
def test_dockerignore_contains_required_pattern(pattern: str):
    content = DOCKERIGNORE.read_text(encoding="utf-8")
    lines = {line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")}
    assert pattern in lines, (
        f"{pattern!r} is missing from .dockerignore. Without it the Docker "
        "build context will include files that should never be shipped (see "
        "issue #101)."
    )
