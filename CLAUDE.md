# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FastAPI-based MCP multiplexer that exposes many MCP servers (process + Docker Gateway) through two transports:
- **Streamable HTTP** at `http://localhost:9400/mcp/` — for Codex and Claude Code (recommended)
- **SSE** at `http://localhost:9400/sse` — for Gemini CLI, Cursor, Windsurf

Dynamic MCP mode (default) exposes 4 meta-tools (`airis-find`, `airis-schema`, `airis-workflow`, `airis-exec`) plus every discoverable COLD server's indexed tools with a lazy stub schema (`{"type":"object"}`), instead of 60+ fully-schema'd raw tools. A client that only reads `tools/list` can call a COLD tool by name directly — the server auto-discovers and auto-enables it on first call, one hop, no meta-tool round trip. `airis-find`/`airis-schema` remain available as an optional discovery aid (server browsing, full schemas); `airis-exec` remains as the compat router for older clients. Set `COLD_TOOLS_IN_LIST=false` to restore the old meta-tool-only listing for context-constrained clients.

Source of truth for server config: `mcp-config.json` (runtime) and `workflows/*.yaml`. Workflows split by `compile_to`: `mcp_instructions` ones are baked into the MCP `initialize` instructions by `apps/api/src/app/core/behavior_compiler.py`; `airis_workflow` ones are served on-demand by the `airis-workflow` meta-tool keyed by `topic`.

## Repo layout

- `apps/api/` — Python 3.12 + FastAPI gateway (uv-managed). The actual MCP multiplexer.
- `apps/gateway-control/` — TypeScript MCP server exposing gateway control tools to agents.
- `apps/airis-commands/` (`@airis/commands`) — TypeScript MCP server bundling slash-command tooling.
- `mcp-config.json` — runtime server registry (HOT/COLD, tools index, behavior).
- `workflows/*.yaml` — behavior recipes. `compile_to: mcp_instructions` → baked into `initialize`; `compile_to: airis_workflow` (named `airis-workflow-<topic>.yaml`) → served on-demand via the `airis-workflow` meta-tool.
- `docs/architecture.md` — current + target architecture (the old root `ARCHITECTURE.md` was moved here).
- `manifest.toml` + `airis gen` produce `package.json` etc. Do not hand-edit files that carry a `DO NOT EDIT` header.

## Commands

All commands use go-task inside `devbox shell`. Run `task --list-all` for the full list.

Most used: `task docker:up` / `task docker:down` / `task docker:logs` / `task docker:restart` / `task test:e2e` / `task test:api`.

There is a single root `compose.yaml` (no `.dev`/`.dist` overrides). It declares both `image:` (GHCR) and `build:` with `pull_policy: missing`, so `task docker:up` pulls the prebuilt image (end users) while `task dev:up` rebuilds from local source (`docker compose up -d --build`, for contributors). Both bind port 9400 — stop one before starting the other. After editing `apps/api/src/` or a bundled TS server, re-run `task dev:up` to rebuild.

Test layout under `apps/api/tests/`:
- `unit/` — pure logic, no network. Default target for `task test:api`.
- `integration/` — exercises FastAPI app + ProcessManager with stubbed subprocesses.
- `e2e/` — boots the full Docker stack and hits `localhost:9400`. Driven by `task test:e2e`.

Python tests locally without Docker: `cd apps/api && uv pip install -e ".[test]" && uv run python -m pytest tests/unit -v`. Run a single test with `uv run python -m pytest tests/unit/test_foo.py::test_bar -v`.

## Updating bundled `airis` CLI

The gateway image bakes a specific `airis-workspace` release. To bump it:

1. Edit `AIRIS_VERSION` in `Dockerfile` (single source of truth — the version is pulled at build time from the airis-workspace GitHub release).
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

- **HOT**: ProcessManager process servers (uvx/npx/airis) always listed in `tools/list` with full schema — pre-warmed at API startup, never idle-killed. Default HOT set: `context7`, `airis-mcp-gateway-control`, `airis-workspace`.
- **COLD**: Docker Gateway backend servers — listed directly in `tools/list` with a lazy stub schema (`COLD_TOOLS_IN_LIST=true`, default) via each server's `tools_index`; auto-discovered and auto-enabled on first `tools/call`.

In DYNAMIC_MCP mode, `tools/list` returns meta-tools + HOT server tools (full schema) + discoverable COLD server tools (stub schema, `{"type":"object"}`). `airis-find` remains available for browsing servers/tools and `airis-schema` for full schemas on demand.

The `airis` CLI itself is baked into the gateway image (see `Dockerfile`, fetched from the airis-workspace GitHub release pinned via `AIRIS_VERSION`), so `airis-workspace`'s 27 tools (`workspace_init`, `workspace_gen`, `workspace_doctor`, `workspace_status`, `manifest_validate`, `manifest_apply`, `migration_execute`, etc.) are available out of the box without host installation. The gateway container mounts `${HOST_WORKSPACE_DIR:-${HOME}/github}` at `/workspace` so those tools can operate on real projects.

Note on JSON-RPC tolerance: airis-workspace emits `"error": null` alongside successful results. The gateway treats that as "no error" (see `process_runner._initialize` and the `tools/call` paths in `mcp_proxy.py` / `process_mcp.py`). New servers with the same quirk will work transparently.

### Schema partitioning

`apply_schema_partitioning()` strips verbose JSON schemas from `tools/list` and injects a synthetic `expandSchema` tool. Clients call `expandSchema` on-demand to get the full schema for a specific tool. Saves significant tokens per `initialize`.

### Streamable HTTP bridge internals

`_open_stream_bridge_session()` opens a persistent GET `/sse` to Docker Gateway, reads the endpoint URL via `__anext__()` (NOT `async for ... break` — that calls `aclose()`), then passes the same iterator to `_stream_bridge_reader()` which drains SSE events into a queue. `send_via_stream_bridge()` POSTs to the backend, then waits on the queue for the matching response id.

## Dynamic MCP

`DYNAMIC_MCP=true` (default) exposes 4 meta-tools — `airis-find` (discover tools/servers), `airis-schema` (get a tool's full input schema), `airis-workflow` (fetch a task-specific procedure by `topic`), `airis-exec` (compat router: execute any tool by name/`server:tool`) — plus, when `COLD_TOOLS_IN_LIST=true` (default), every discoverable COLD server's `tools_index` entries with a lazy stub schema. The primary path for a COLD tool is now a direct `tools/call` with the name learned from `tools/list`; the server auto-discovers and auto-enables on that first call, same as before. `airis-exec` is kept for clients that can't act on a bare `tools/list` name. `META_TOOLS_MODE=full` adds `airis-confidence`, `airis-repo-index`, `airis-suggest`, `airis-route`.

Instructions returned on `initialize` are compiled from the `compile_to: mcp_instructions` `workflows/*.yaml` — **edit the YAML, not the Python**. Each needs `name`, `compile_to`, `priority`, and a `text:` block. Missing `text` makes it emit literal `compile_to` values (bug: 2026-04-14).

On-demand workflows use `compile_to: airis_workflow` plus a `topic:` key (matching the `airis-workflow` tool's `topic` enum); they are NOT dumped into `initialize` — the agent fetches them by calling `airis-workflow` with that topic. Handler: `handle_airis_workflow()` in `apps/api/src/app/api/endpoints/mcp_proxy.py`.

## Tool Routing Guide

When working in a project that uses this gateway, pick tools by this decision flow:

```
Need official library docs?    → context7:resolve-library-id → context7:query-docs
Need current/external info?    → tavily:tavily-search
Database query or schema?      → supabase is disabled by default (not authorized); do not call supabase:* unless a human has explicitly enabled it
Payment/billing?               → stripe:*
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
   Registering as a user-scoped MCP server is the only install method — there is no separate plugin. Codex uses Streamable HTTP at `http://localhost:9400/mcp/`. Claude Desktop is intentionally unmanaged.
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

Releasing: `VERSION` is the source of truth. Bump it (run `task version:sync` to propagate to the package manifests) in a normal PR; on merge `release.yml` tags the commit `v<VERSION>` and publishes a GitHub Release (once per version). The release workflow only reads `VERSION` and creates the tag/Release with `GITHUB_TOKEN` — it never opens a PR, so no GitHub App is involved.
