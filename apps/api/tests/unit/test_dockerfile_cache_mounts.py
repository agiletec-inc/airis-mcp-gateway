"""
Regression test for issue #109 / #81: Dockerfile build-cache layering.

f4646b45 (#109) added BuildKit cache mounts for apt, pip/uv, and the package
manager, and ordered manifests before src/ so source-only changes reuse the
cached install layer. #81 then migrated the TypeScript apps onto a pnpm
workspace and consolidated the build into the single repo-root Dockerfile.

This is a static guard over the repo-root Dockerfile:
- `# syntax=docker/dockerfile:1.x` header must be present (BuildKit required).
- An apt cache mount (`--mount=type=cache,target=/var/cache/apt`).
- A uv cache mount (`--mount=type=cache,target=/root/.cache/uv`).
- A pnpm store cache mount (`--mount=type=cache,target=/pnpm/store`).
- The pnpm workspace manifests are COPYed BEFORE the src/ trees.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "Dockerfile"

TS_APPS = ["gateway-control", "airis-commands"]

# CI runs pytest from a full repo checkout; inside the api container only
# apps/api/src is available, so the Dockerfile path does not resolve. Skip
# the module so the Docker-internal smoke run stays green; CI is the
# authoritative gate.
if not DOCKERFILE.exists():
    pytest.skip(
        f"Dockerfile not reachable from {DOCKERFILE} — likely running inside "
        "the api container, skipping. CI on a full repo checkout provides "
        "the real gate.",
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


def test_dockerfile_has_pnpm_store_cache_mount():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "--mount=type=cache,target=/pnpm/store" in text, (
        "pnpm store cache mount missing from Dockerfile — the TypeScript "
        "workspace install will not reuse the store on warm builds "
        "(issue #109 / #81)."
    )


def test_dockerfile_copies_workspace_manifests_before_src():
    """The pnpm workspace manifests (lockfile + per-app package.json) must be
    COPYed BEFORE the src/ trees so a source-only change reuses the cached
    `pnpm install --frozen-lockfile` layer. If src/ is copied first, every
    .ts edit invalidates the install layer and rebuilds from scratch."""
    text = DOCKERFILE.read_text(encoding="utf-8")

    lock_match = re.search(r"COPY\s+[^\n]*pnpm-lock\.yaml", text)
    assert lock_match, "Missing a `COPY ... pnpm-lock.yaml` in Dockerfile (issue #81)."

    first_src = min(
        (m.start() for m in re.finditer(r"COPY\s+apps/\S+/src\b", text)),
        default=-1,
    )
    assert first_src != -1, "No `COPY apps/*/src` found in Dockerfile."
    assert lock_match.start() < first_src, (
        "pnpm-lock.yaml must be COPYed before the src/ trees so source-only "
        "changes reuse the cached pnpm install layer (issue #81)."
    )

    for app in TS_APPS:
        pkg_match = re.search(rf"COPY\s+apps/{re.escape(app)}/package\.json", text)
        src_match = re.search(rf"COPY\s+apps/{re.escape(app)}/src\b", text)
        assert pkg_match, f"Missing `COPY apps/{app}/package.json ...` (issue #81)."
        assert src_match, f"Missing `COPY apps/{app}/src ...` (issue #81)."
        assert pkg_match.start() < src_match.start(), (
            f"apps/{app}/package.json must be COPYed before apps/{app}/src "
            f"(issue #81)."
        )
