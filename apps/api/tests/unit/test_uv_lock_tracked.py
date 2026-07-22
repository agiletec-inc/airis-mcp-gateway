"""
Regression test for issue #192: commit uv.lock and use frozen installs.

Before this fix, `.gitignore` ignored `uv.lock`, so CI (`uv pip install
--system -e ".[test]"`) and Docker (`uv pip install --system -e .`) both
fresh-resolved Python dependencies on every build. That's how the FastAPI
0.137 breakage surfaced silently — nothing pinned the exact resolved graph.
This is a static guard that fails (not skips) if any part of the fix
regresses: the lockfile must exist and be git-tracked, `.gitignore` must not
ignore it again, and both CI and the Dockerfile must install from it with
`--frozen` (or gate on `uv lock --check`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# apps/api/tests/unit/ -> apps/api/tests -> apps/api -> apps -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
UV_LOCK = REPO_ROOT / "apps" / "api" / "uv.lock"
GITIGNORE = REPO_ROOT / ".gitignore"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"

# CI runs pytest from a full repo checkout; inside the api container only
# apps/api/src is available, so repo-root paths do not resolve. Fail loudly
# there is no legitimate reason for these paths to be missing when the repo
# is fully checked out — only skip when we can positively detect we are NOT
# looking at a full checkout (i.e. the repo root itself isn't a git repo).
if not (REPO_ROOT / ".git").exists():
    pytest.skip(
        f"{REPO_ROOT} is not a full repo checkout (no .git) — likely running "
        "inside the api container, skipping. CI on a full repo checkout "
        "provides the real gate.",
        allow_module_level=True,
    )


def test_uv_lock_exists():
    assert UV_LOCK.is_file(), (
        f"{UV_LOCK} is missing. Generate it with `cd apps/api && uv lock` "
        "and commit it (issue #192)."
    )


def test_uv_lock_is_git_tracked():
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "apps/api/uv.lock"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "apps/api/uv.lock exists but is not git-tracked. Commit it so builds "
        "are reproducible (issue #192). git output: "
        f"{result.stdout!r} {result.stderr!r}"
    )


def test_gitignore_does_not_ignore_uv_lock():
    assert GITIGNORE.is_file(), f"{GITIGNORE} is missing"
    lines = {
        line.strip()
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert "uv.lock" not in lines, (
        ".gitignore ignores uv.lock again — this makes Python builds "
        "non-reproducible (issue #192). Do not re-add it."
    )


def test_ci_workflow_uses_frozen_install():
    assert CI_WORKFLOW.is_file(), f"{CI_WORKFLOW} is missing"
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "--frozen" in text, (
        f"{CI_WORKFLOW} no longer installs Python deps with --frozen — CI "
        "must install from the committed uv.lock, not re-resolve (issue #192)."
    )
    assert "uv lock --check" in text, (
        f"{CI_WORKFLOW} is missing a `uv lock --check` step — CI must fail "
        "when uv.lock and pyproject.toml have drifted apart (issue #192)."
    )


def test_dockerfile_uses_frozen_install():
    assert DOCKERFILE.is_file(), f"{DOCKERFILE} is missing"
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "--frozen" in text, (
        f"{DOCKERFILE} no longer installs Python deps with --frozen — the "
        "image must build from the committed uv.lock, not re-resolve "
        "(issue #192)."
    )
