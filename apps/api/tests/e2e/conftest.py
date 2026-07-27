"""
Shared helpers for e2e tests (require the live Docker stack).
"""

import os

import pytest


def skip_or_fail(reason: str) -> None:
    """Skip a flaky/timeout-prone e2e assertion, unless E2E_STRICT=1.

    Casual local runs (`pytest tests/e2e -v` against a stack that hasn't
    fully warmed up COLD servers yet) still skip so devs aren't blocked by
    infra flakiness. The documented e2e entrypoint (`task test:e2e`) sets
    E2E_STRICT=1 so the same timeouts fail the run instead of silently
    passing — a green `task test:e2e` should mean the stack is actually
    healthy, not that everything timed out and skipped (issue #195).
    """
    if os.getenv("E2E_STRICT") == "1":
        pytest.fail(f"[E2E_STRICT] {reason}")
    pytest.skip(reason)
