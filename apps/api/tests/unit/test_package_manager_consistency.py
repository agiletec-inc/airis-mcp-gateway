"""
Regression test for issue #81: consistent package manager across the repo.

The TypeScript apps (gateway-control, airis-commands) were migrated from
per-app npm to a single pnpm workspace, and the build was consolidated into
one repo-root Dockerfile (the dead legacy root Dockerfile was removed). These
static guards keep the repo from drifting back into a pnpm/npm mix:

- exactly one Dockerfile, at the repo root
- the pnpm workspace scaffolding exists (pnpm-workspace.yaml, root package.json,
  pnpm-lock.yaml)
- no npm lockfiles anywhere
- the Dockerfile does not build the unused pnpm workspace or use `npm ci`
- the per-app package.json files do not pin npm as packageManager
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "Dockerfile"
TS_APPS = ["gateway-control", "airis-commands"]

# CI runs pytest from a full repo checkout; inside the api container only
# apps/api/src is available, so repo paths do not resolve. Skip the module
# there so the Docker-internal smoke run stays green — CI is the real gate.
#
# The skip condition checks `.git` (an environment signal independent of the
# guarded files), NOT `DOCKERFILE.exists()` itself. If it checked a guarded
# file directly, a real regression (Dockerfile/lockfile deleted or moved in a
# full checkout) would silently skip instead of failing (issue #195).
if not (REPO_ROOT / ".git").exists():
    pytest.skip(
        f"{REPO_ROOT} is not a full repo checkout (no .git) — likely running "
        "inside the api container, skipping. CI on a full repo checkout is "
        "the gate.",
        allow_module_level=True,
    )


def test_single_dockerfile_at_repo_root():
    assert DOCKERFILE.is_file(), "repo-root Dockerfile is missing"
    assert not (REPO_ROOT / "apps" / "api" / "Dockerfile").exists(), (
        "apps/api/Dockerfile reappeared — the build is consolidated into the "
        "single repo-root Dockerfile (issue #81)."
    )


def test_pnpm_workspace_scaffolding_exists():
    assert (REPO_ROOT / "pnpm-workspace.yaml").is_file(), (
        "pnpm-workspace.yaml missing — TS apps use a pnpm workspace (issue #81)."
    )
    assert (REPO_ROOT / "package.json").is_file(), (
        "root package.json missing — required for the pnpm workspace (issue #81)."
    )
    assert (REPO_ROOT / "pnpm-lock.yaml").is_file(), (
        "pnpm-lock.yaml missing — commit the workspace lockfile (issue #81)."
    )


def test_no_npm_lockfiles():
    assert not (REPO_ROOT / "package-lock.json").exists(), (
        "package-lock.json at repo root — the repo standardised on pnpm (issue #81)."
    )
    for app in TS_APPS:
        assert not (REPO_ROOT / "apps" / app / "package-lock.json").exists(), (
            f"apps/{app}/package-lock.json exists — remove it; the repo uses "
            f"a pnpm workspace (issue #81)."
        )


def test_dockerfile_does_not_build_unused_javascript_servers():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "pnpm install --frozen-lockfile" not in text, (
        "Dockerfile still builds the removed TypeScript MCP servers"
    )
    assert "npm ci" not in text, (
        "Dockerfile still runs `npm ci` — the TS apps build with pnpm (issue #81)."
    )


def test_root_package_json_declares_pnpm():
    pkg = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    package_manager = pkg.get("packageManager", "")
    assert package_manager.startswith("pnpm@"), (
        f"root package.json declares packageManager={package_manager!r}; it "
        f"must be pnpm (issue #81)."
    )


@pytest.mark.parametrize("app", TS_APPS)
def test_ts_app_package_json_has_no_npm_package_manager(app):
    pkg = json.loads(
        (REPO_ROOT / "apps" / app / "package.json").read_text(encoding="utf-8")
    )
    package_manager = pkg.get("packageManager", "")
    assert not package_manager.startswith("npm@"), (
        f"apps/{app}/package.json declares packageManager={package_manager!r}; "
        f"the workspace uses pnpm and the root package.json owns this field "
        f"(issue #81)."
    )
