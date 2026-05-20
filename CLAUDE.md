# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FastAPI-based MCP multiplexer that exposes many MCP servers (process + Docker Gateway) through two transports:
- **Streamable HTTP** at `http://localhost:9400/mcp/` — for Codex and Claude Code (recommended)
- **SSE** at `http://localhost:9400/sse` — for Gemini CLI, Cursor, Windsurf

Dynamic MCP mode (default) exposes only 2 meta-tools (`airis-find`, `airis-schema`) instead of 60+ raw tools. COLD servers auto-discover and auto-enable on first native tool call — no router wrapper needed.

Source of truth for server config: `mcp-config.json` (runtime) and `workflows/*.yaml` (compiled into MCP `initialize` instructions by `apps/api/src/app/core/behavior_compiler.py`).

## Repo layout

- `apps/api/` — Python 3.12 + FastAPI gateway (uv-managed). The actual MCP multiplexer.
- `apps/gateway-control/` — TypeScript MCP server exposing gateway control tools to agents.
- `apps/airis-commands/` (`@airis/commands`) — TypeScript MCP server bundling slash-command tooling.
- `mcp-config.json` — runtime server registry (HOT/COLD, tools index, behavior).
- `workflows/*.yaml` — compiled into MCP `initialize` instructions.
- `manifest.toml` + `airis gen` produce `compose.yaml`, `package.json`, etc. Do not hand-edit generated files.

## Commands

All commands use go-task inside `devbox shell`. Run `task --list-all` for the full list.

Most used: `task docker:up` / `task docker:down` / `task docker:logs` / `task docker:restart` / `task test:e2e` / `task test:api`.

Test layout under `apps/api/tests/`:
- `unit/` — pure logic, no network. Default target for `task test:api`.
- `integration/` — exercises FastAPI app + ProcessManager with stubbed subprocesses.
- `e2e/` — boots the full Docker stack and hits `localhost:9400`. Driven by `task test:e2e`.

Python tests locally without Docker: `cd apps/api && uv pip install -e ".[test]" && uv run python -m pytest tests/unit -v`. Run a single test with `uv run python -m pytest tests/unit/test_foo.py::test_bar -v`.

## Updating bundled `airis` CLI

The gateway image bakes a specific `airis-workspace` release. To bump it:

1. Edit `AIRIS_VERSION` in `apps/api/Dockerfile` (single source of truth — the version is pulled at build time from the airis-workspace GitHub release).
2. `task docker:build` (or `docker compose build api`) — verify the Dockerfile download step succeeds.
3. `task docker:up` and confirm `airis-workspace` tools resolve via `airis-find`.
4. Commit `Dockerfile` only — there is no `package.json` pin to keep in sync.

## Architecture

### Transport layer

The API in `apps/api/src/app/api/endpoints/` is split into focused modules:

| Module | Responsibility |
|--------|---------------|
| `gateway_stream_bridge.py` | Bridges Streamable HTTP clients → Docker Gateway SSE. Holds `StreamBridgeSession` (httpx client + SSE stream + asyncio.Queue + background reader task). 15-min idle TTL. |
| `session_queue.py` | Per-session `asyncio.Queue` for classic SSE proxy responses. 10-min idle TTL. |
| `sse_protocol.py` | Pure wire-format helpers: `format_sse_event()`, `parse_sse_json()`, `SSEEventBuffer`. No I/O. |
| `tool_shaping.py` | Rewrites `tools/list` and `prompts/list` responses: schema partitioning, description modes (FULL/SUMMARY/BRIEF/NONE via `DESCRIPTION_MODE` env), HOT/COLD split, meta-tool injection. |
| `mcp_proxy.py` | Main router. Imports from sibling modules. Decision at `_proxy_jsonrpc_request()`: if no `sessionid` query param → `send_via_stream_bridge()` for Streamable HTTP; otherwise classic SSE proxy. |

### HOT/COLD server split

- **HOT**: ProcessManager process servers (uvx/npx/airis) always listed in `tools/list` — pre-warmed at API startup, never idle-killed. Default HOT set: `context7`, `airis-mcp-gateway-control`, `airis-workspace`.
- **COLD**: Docker Gateway backend servers — not listed directly; auto-discovered via tools index on first native tool call, enabled on-demand.

In DYNAMIC_MCP mode, `tools/list` returns only meta-tools + currently active HOT server tools. Full tool discovery goes through `airis-find`.

The `airis` CLI itself is baked into the gateway image (see `apps/api/Dockerfile`, fetched from the airis-workspace GitHub release pinned via `AIRIS_VERSION`), so `airis-workspace`'s 11 tools (`workspace_init`, `workspace_gen`, `workspace_doctor`, `workspace_status`, `manifest_validate`, `manifest_apply`, `migration_execute`, etc.) are available out of the box without host installation. The gateway container mounts `${HOST_WORKSPACE_DIR:-${HOME}/github}` at `/workspace` so those tools can operate on real projects.

Note on JSON-RPC tolerance: airis-workspace emits `"error": null` alongside successful results. The gateway treats that as "no error" (see `process_runner._initialize` and the `tools/call` paths in `mcp_proxy.py` / `process_mcp.py`). New servers with the same quirk will work transparently.

### Schema partitioning

`apply_schema_partitioning()` strips verbose JSON schemas from `tools/list` and injects a synthetic `expandSchema` tool. Clients call `expandSchema` on-demand to get the full schema for a specific tool. Saves significant tokens per `initialize`.

### Streamable HTTP bridge internals

`_open_stream_bridge_session()` opens a persistent GET `/sse` to Docker Gateway, reads the endpoint URL via `__anext__()` (NOT `async for ... break` — that calls `aclose()`), then passes the same iterator to `_stream_bridge_reader()` which drains SSE events into a queue. `send_via_stream_bridge()` POSTs to the backend, then waits on the queue for the matching response id.

## Dynamic MCP

`DYNAMIC_MCP=true` (default) exposes 2 meta-tools: `airis-find` (discover tools), `airis-schema` (get input schema). `META_TOOLS_MODE=full` adds `airis-confidence`, `airis-repo-index`, `airis-suggest`, `airis-route`. COLD servers auto-discover and auto-enable on first native tool call — no router wrapper needed.

Instructions returned on `initialize` are compiled from `workflows/*.yaml` — **edit the YAML, not the Python**. Each workflow needs `name`, `compile_to: mcp_instructions`, `priority`, and a `text:` block. Missing `text` makes it emit literal `compile_to` values (bug: 2026-04-14).

## Tool Routing Guide

When working in a project that uses this gateway, pick tools by this decision flow:

```
Need official library docs?    → context7:resolve-library-id → context7:get-library-docs
Need current/external info?    → tavily:tavily-search
Database query or schema?      → supabase:query
Payment/billing?               → stripe:*
DNS/workers/KV?                → cloudflare:*
Figma/design?                  → figma:*
Browser testing/screenshots?   → playwright-cli skill (host Chrome — NOT MCP playwright)
File generation (docx/xlsx/…)? → claude-api plugin (host filesystem)
TDD/debugging/planning?        → superpowers plugin
Git operations?                → gh CLI or native git
Simple code read/edit/search?  → native Read, Edit, Grep, Glob (no MCP)
```

Complexity rule of thumb:
- **Simple** (1–2 known files): native tools only.
- **Medium** (new library, need docs): context7 first, then native tools.
- **Complex** (multi-service, research): `airis-route` to get an optimal chain.

What NOT to route through the Gateway:
- Browser automation — needs host Chrome, Docker image has none. Use `playwright-cli` skill.
- File generation (docx/xlsx/pdf) — needs host filesystem. Use `claude-api` plugin.
- Git — `gh` CLI and native git are more reliable than any MCP wrapper.

## Design principles

1. **Global registration via CLI only.** Register once as a user-scoped MCP server (Streamable HTTP):
   ```bash
   claude mcp add --transport http --scope user airis-gateway http://localhost:9400/mcp/
   ```
   Do NOT also use `/install-plugin` — duplicate endpoint causes the plugin's MCP connection to be silently ignored. Codex uses Streamable HTTP at `http://localhost:9400/mcp/`. Claude Desktop is intentionally unmanaged.
2. **All MCP servers go through the gateway.** Users do not register individual servers. Add new ones to `mcp-config.json`. Repo-local `mcp.json` is forbidden after migration — use `airis-gateway import <dir> --apply` + `airis-gateway clean <dir>` to migrate.
3. **Auto-start on boot.** `task autostart:install` creates a macOS LaunchAgent or Linux systemd user unit. `task autostart:status` to verify.

## Debugging

```bash
task docker:logs                              # follow API logs
curl http://localhost:9400/health             # quick check
curl http://localhost:9400/process/servers    # list process servers
curl http://localhost:9400/metrics            # Prometheus metrics
```

Common issues:
- **Server not found** → check `mcp-config.json`, run `task docker:restart`.
- **Timeout** → check `TOOL_CALL_TIMEOUT` env, server may be slow to start.
- **Circuit open** → server crashed repeatedly, check logs for root cause.
- **Instructions look wrong** → compare `docker compose exec api python -c "from app.core.behavior_compiler import compile_instructions; from app.core.mcp_config_loader import load_mcp_config; print(compile_instructions(load_mcp_config().servers))"` against the YAMLs. If they diverge, rebuild the image — coded changes to `behavior_compiler.py` / `workflow_loader.py` need `docker compose build api`.
- **Stream bridge "content already streamed"** → symptom of `async for ... break` on httpx SSE iterator calling `aclose()`. Fix: use `__anext__()` directly and pass the same iterator to the reader task.

## Screenshot verification

Use the `playwright-cli` skill (host Chrome, headless). Flow: `playwright-cli open <url>` → `playwright-cli snapshot` (YAML, token-efficient — prefer over screenshot unless visual check is required). Do NOT use the MCP Playwright server (no Chrome in Docker).

## CI/CD

Path-based triggers:
- `apps/api/**` → Python tests (pytest)
- `apps/gateway-control/**` or `apps/airis-commands/**` → TypeScript build
