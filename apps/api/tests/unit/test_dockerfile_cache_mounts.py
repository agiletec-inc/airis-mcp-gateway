"""
Regression test for issue #109 / #81: Dockerfile build-cache layering.

f4646b45 (#109) added BuildKit cache mounts for apt, pip/uv, and the package
manager, and ordered manifests before src/ so source-only changes reuse the
cached install layer. The gateway no longer bundles TypeScript MCP servers,
so its runtime image must not build the pnpm workspace.

This is a static guard over the repo-root Dockerfile:
- `# syntax=docker/dockerfile:1.x` header must be present (BuildKit required).
- An apt cache mount (`--mount=type=cache,target=/var/cache/apt`).
- A uv cache mount (`--mount=type=cache,target=/root/.cache/uv`).
- No pnpm workspace install or source copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "Dockerfile"

# CI runs pytest from a full repo checkout; inside the api container only
# apps/api/src is available, so the Dockerfile path does not resolve. Skip
# the module there so the Docker-internal smoke run stays green; CI is the
# authoritative gate.
#
# The skip condition checks `.git` (an environment signal independent of the
# guarded file), NOT `DOCKERFILE.exists()` itself. If it checked the guarded
# file directly, a real regression (Dockerfile deleted/moved in a full
# checkout) would silently skip instead of failing (issue #195).
if not (REPO_ROOT / ".git").exists():
    pytest.skip(
        f"{REPO_ROOT} is not a full repo checkout (no .git) — likely running "
        "inside the api container, skipping. CI on a full repo checkout "
        "provides the real gate.",
        allow_module_level=True,
    )


def test_dockerfile_exists():
    assert DOCKERFILE.is_file(), f"{DOCKERFILE} is missing"


def test_dockerfile_has_buildkit_syntax_header():
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    # Header must be the very first line (Docker requires this for BuildKit
    # features like --mount=type=cache to be recognised).
    assert lines, "Dockerfile is empty"
    assert re.match(r"^# syntax=docker/dockerfile:1\.\d", lines[0]), (
        "Dockerfile is missing the `# syntax=docker/dockerfile:1.x` header; "
        "BuildKit cache mounts will be ignored without it (issue #109)."
    )


def test_dockerfile_has_apt_cache_mount():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "--mount=type=cache,target=/var/cache/apt" in text, (
        "apt cache mount missing from Dockerfile (issue #109)."
    )


def test_dockerfile_has_uv_cache_mount():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "--mount=type=cache,target=/root/.cache/uv" in text, (
        "uv cache mount missing from Dockerfile — Python dep installs will "
        "not reuse the cache on warm builds (issue #109)."
    )


def test_dockerfile_does_not_build_the_unused_pnpm_workspace():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "--mount=type=cache,target=/pnpm/store" not in text, (
        "the minimal Gateway image must not retain a pnpm cache for unused "
        "TypeScript MCP servers"
    )
    assert "pnpm install --frozen-lockfile" not in text
