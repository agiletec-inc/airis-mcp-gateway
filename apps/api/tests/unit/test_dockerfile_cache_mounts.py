"""
Regression test for issue #109: Dockerfile rebuilds TypeScript apps without
cache mounts.

f4646b45 added BuildKit cache mounts for apt, pip/uv, and npm, and reordered
package.json/tsconfig to be COPYed before src/ so source-only changes reuse
the cached layer. If any of those mounts are removed, warm builds regress
from seconds to minutes.

This is a static guard over apps/api/Dockerfile:
- `# syntax=docker/dockerfile:1.x` header must be present (BuildKit required).
- At least one `--mount=type=cache,target=/var/cache/apt` (apt layer).
- At least one `--mount=type=cache,target=/root/.cache/uv` (Python deps).
- At least two `--mount=type=cache,target=/root/.npm` (one per TS app build).
- For each TS app, `COPY package*.json` must appear BEFORE `COPY .../src`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "apps" / "api" / "Dockerfile"

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


def _dockerfile_lines() -> list[str]:
    return DOCKERFILE.read_text(encoding="utf-8").splitlines()


def test_dockerfile_exists():
    assert DOCKERFILE.is_file(), f"{DOCKERFILE} is missing"


def test_dockerfile_has_buildkit_syntax_header():
    lines = _dockerfile_lines()
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


def test_dockerfile_has_npm_cache_mounts_for_each_ts_app():
    text = DOCKERFILE.read_text(encoding="utf-8")
    npm_mount_count = text.count("--mount=type=cache,target=/root/.npm")
    assert npm_mount_count >= len(TS_APPS), (
        f"Expected at least {len(TS_APPS)} `--mount=type=cache,target=/root/.npm` "
        f"directives (one per TS app build), found {npm_mount_count} (issue #109)."
    )


def test_dockerfile_copies_package_json_before_src_for_each_ts_app():
    """package.json/tsconfig must be COPYed BEFORE src/ so that source-only
    changes reuse the cached `npm ci` layer. If src/ is copied first, every
    .ts edit invalidates the install layer and rebuilds from scratch."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    for app in TS_APPS:
        pkg_match = re.search(rf"COPY\s+apps/{re.escape(app)}/package\*\.json", text)
        src_match = re.search(rf"COPY\s+apps/{re.escape(app)}/src\b", text)
        assert pkg_match, (
            f"Missing `COPY apps/{app}/package*.json ...` in Dockerfile "
            f"(issue #109)."
        )
        assert src_match, (
            f"Missing `COPY apps/{app}/src ...` in Dockerfile (issue #109)."
        )
        assert pkg_match.start() < src_match.start(), (
            f"apps/{app}/package*.json must be COPYed before apps/{app}/src "
            f"so that source-only changes reuse the cached `npm ci` layer "
            f"(issue #109). Current order will invalidate the cache on every "
            f"TypeScript edit."
        )
