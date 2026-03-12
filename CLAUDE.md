# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

All commands use go-task. Enter devbox shell first: `devbox shell`

```bash
# Stack management
task docker:up              # Start gateway + API
task docker:down            # Stop all
task docker:logs            # View API logs
task docker:restart         # Restart after config changes
task docker:clean           # Remove containers and volumes

# Auto-start (boot persistence)
task autostart:install      # Enable auto-start on login (macOS/Linux)
task autostart:uninstall    # Disable auto-start
task autostart:status       # Check auto-start status
task autostart:logs         # View auto-start logs

# Development mode (hot reload)
task dev:up                 # Start with hot reload
task dev:watch              # Auto-rebuild TypeScript on change
task build:mcp              # Build MCP servers manually

# Testing
task test:e2e               # Full end-to-end test
task test:health            # Quick health check
task test:status            # Server status
task test:api               # Run pytest in container

# Local testing (without Docker)
cd apps/api && uv pip install -e ".[test]"
uv run python -m pytest tests/unit -v                      # All unit tests
uv run python -m pytest tests/unit/test_dynamic_mcp.py -v  # Single file
uv run python -m pytest tests/unit -k "test_find"          # By test name

# TypeScript tests
cd apps/gateway-control && pnpm test
cd apps/airis-commands && pnpm test

# All tasks
task --list-all             # Show all available tasks
```

## Project Structure

```
apps/
├── api/                    # FastAPI MCP multiplexer (Python)
│   ├── src/app/
│   │   ├── main.py         # App entry point
│   │   ├── core/           # Business logic (process_manager, dynamic_mcp, circuit)
│   │   ├── api/endpoints/  # REST + SSE handlers (mcp_proxy is the main one)
│   │   ├── models/         # SQLAlchemy models
│   │   ├── schemas/        # Pydantic schemas
│   │   └── crud/           # Database operations
│   └── tests/
│       ├── unit/           # Fast, no Docker required
│       ├── integration/    # Requires database
│       └── e2e/            # Full stack tests
├── gateway-control/        # Gateway management MCP server (TypeScript)
└── airis-commands/         # Config/profile MCP server (TypeScript)
```

## Architecture

```
Claude Code / Cursor / Zed
    │
    ▼ SSE (http://localhost:9400/sse)
┌─────────────────────────────────────────────────────────┐
│  FastAPI Hybrid MCP Multiplexer (port 9400)             │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Dynamic MCP Layer                              │    │
│  │  ├─ airis-find    (discover ALL servers/tools)  │    │
│  │  ├─ airis-exec    (execute + auto-enable)       │    │
│  │  └─ airis-schema  (get tool input schema)       │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  ProcessManager (Lazy start + idle-kill)        │    │
│  │  ├─ gateway-control (node)  HOT                 │    │
│  │  ├─ airis-commands (node)   HOT                 │    │
│  │  ├─ airis-agent (uvx)       COLD                │    │
│  │  ├─ memory (npx)            COLD                │    │
│  │  ├─ stripe (npx)            COLD                │    │
│  │  ├─ supabase (npx)          COLD                │    │
│  │  └─ ... (20+ more servers)                      │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Docker Gateway (9390) - mindbase, etc.         │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

**Key patterns:**
- **Dynamic MCP** (default): Only 3 meta-tools exposed (airis-find, airis-exec, airis-schema)
- **Auto-enable**: Disabled servers are auto-enabled when airis-exec is called
- **Lazy loading**: Process servers start on first request, not at startup
- **Idle-kill**: Unused servers terminate after 120s (configurable)
- **Tool routing**: ProcessManager maps tool names to server names dynamically

## Dynamic MCP Mode

By default, `DYNAMIC_MCP=true` exposes only 3 meta-tools instead of 60+:

| Tool | Purpose |
|------|---------|
| `airis-find` | Search tools/servers (including disabled ones) |
| `airis-exec` | Execute tool by name (auto-enables disabled servers) |
| `airis-schema` | Get full input schema for a tool |

All other tools (HOT and COLD) are accessed via `airis-exec`. This follows the [Lasso MCP Gateway](https://github.com/lasso-security/mcp-gateway) pattern.

**Auto-Enable Flow:**
```
airis-find query="stripe"
→ stripe (cold, disabled): 50 tools

airis-exec tool="stripe:create_customer" arguments={...}
→ Server auto-enabled → Tools loaded → Executed!
```

**Token savings:** ~98% reduction (42k → 600 tokens)

To disable and expose all tools directly:
```bash
DYNAMIC_MCP=false docker compose up -d
```

## Key Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | gateway (9390) + api (9400) containers |
| `mcp-config.json` | Server definitions: command, args, env, enabled, mode, TTL |
| `apps/api/src/app/main.py` | FastAPI app entry point |
| `apps/api/src/app/core/process_manager.py` | Manages uvx/npx servers |
| `apps/api/src/app/core/process_runner.py` | Subprocess lifecycle + timeout handling |
| `apps/api/src/app/core/dynamic_mcp.py` | Dynamic MCP meta-tools + auto-enable logic |
| `apps/api/src/app/core/mcp_config_loader.py` | Parse mcp-config.json + TTL settings |
| `apps/api/src/app/api/endpoints/mcp_proxy.py` | SSE proxy + airis-find/exec/schema handlers |
| `apps/api/src/app/core/circuit.py` | Circuit breaker for failing servers |
| `apps/api/src/app/core/credentials_provider.py` | Secure credential injection |
| `apps/api/tests/unit/conftest.py` | Test fixtures and mocks |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/sse` | SSE endpoint for Claude Code |
| `/health` | Health check |
| `/process/servers` | List process servers |
| `/api/tools/combined` | All tools from all sources |
| `/api/tools/status` | Server status overview |
| `/metrics` | Prometheus metrics |

## mcp-config.json Format

```json
{
  "mcpServers": {
    "server-name": {
      "command": "uvx|npx|sh|node",
      "args": ["arg1", "arg2"],
      "env": { "KEY": "value" },
      "enabled": true,
      "mode": "hot|cold",
      "idle_timeout": 120,
      "min_ttl": 60,
      "max_ttl": 3600
    }
  }
}
```

- **command types**: `uvx` (Python), `npx` (Node.js), `sh` (Docker via shell), `node` (direct)
- **mode**: `hot` (always loaded), `cold` (lazy loaded on demand)
- **enabled**: `true` (active), `false` (discoverable but auto-enabled on use)

## Design Principles

### 1. Global Registration Only
- MCP Gateway MUST be registered globally (`--scope user`), NOT per-project
- Command: `claude mcp add --scope user --transport sse airis-mcp-gateway http://localhost:9400/sse`

### 2. ALL MCP Servers Through Gateway
- All servers go through gateway - users don't register individual MCP servers
- Dynamic enable/disable via `airis-exec` (auto-enable on use)
- Add new servers to `mcp-config.json`, NOT as separate registrations

### 3. One-Command Install
```bash
cp mcp-config.json.example mcp-config.json  # First time only, customize as needed
docker compose up -d
```
- Register with Claude Code after startup

### 4. Auto-Start on Boot
To ensure the gateway starts automatically on system reboot:
```bash
task autostart:install    # Installs LaunchAgent (macOS) or systemd service (Linux)
task autostart:status     # Verify installation
```

**macOS (OrbStack/Docker Desktop):**
- Creates `~/Library/LaunchAgents/com.agiletec.airis-mcp-gateway.plist`
- Runs `docker compose up -d` on login
- Logs: `~/Library/Logs/airis-mcp-gateway.log`

**Linux:**
- Creates `~/.config/systemd/user/airis-mcp-gateway.service`
- Enables user lingering for boot persistence
- Logs: `journalctl --user -u airis-mcp-gateway.service`

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DYNAMIC_MCP` | `true` | Enable Dynamic MCP (3 meta-tools only) |
| `TOOL_CALL_TIMEOUT` | `90` | Fail-safe timeout (seconds) for MCP tool calls |
| `AIRIS_API_KEY` | *(none)* | API key for bearer auth (disabled if not set) |
| `MCP_GATEWAY_URL` | `http://gateway:9390` | Docker gateway URL |
| `MCP_CONFIG_PATH` | `/app/mcp-config.json` | Server config path |

## Debugging

```bash
# View logs
task docker:logs                                    # Follow API logs
docker compose logs api 2>&1 | grep -i error        # Filter errors
docker compose logs api 2>&1 | grep "server_name"   # Filter by server

# Check server status
curl http://localhost:9400/process/servers | jq     # All servers
curl http://localhost:9400/process/servers/memory   # Specific server
curl http://localhost:9400/metrics                  # Prometheus metrics

# Common issues
# "Server not found" → Check mcp-config.json, run task docker:restart
# "Timeout" → Check TOOL_CALL_TIMEOUT env var, server may be slow to start
# "Circuit open" → Server crashed repeatedly, check logs for root cause
```

## MCP Server Instructions

The gateway automatically injects `instructions` into the MCP `initialize` response. This guides LLMs on how to use Dynamic MCP:

```
"instructions": "This is AIRIS MCP Gateway with Dynamic MCP. IMPORTANT: Do NOT call tools directly..."
```

This is implemented in `mcp_proxy.py:405-423` and ensures LLMs always know to use `airis-find` → `airis-schema` → `airis-exec` pattern.

## Claude Code Slash Commands

Built-in commands in `.claude/commands/`:

| Command | Description |
|---------|-------------|
| `/test` | End-to-end test of gateway |
| `/status` | Quick status check |
| `/troubleshoot [issue]` | Diagnose issues |

## Screenshot Verification

- `browser-use` スキル禁止。ホスト側でブラウザプロセスを起動するな
- スクリーンショット検証は Playwright headless を Docker コンテナ内で実行すること
- Playwright 入りの Docker イメージを用意し、コンテナ内で `page.screenshot()` して画像をアーティファクトとして保存
- ホストのプロセステーブルを汚すな

## CI/CD

Path-based CI triggers - only runs relevant jobs:
- `apps/api/**` changes → Python tests (pytest)
- `apps/gateway-control/**` or `apps/airis-commands/**` changes → TypeScript build
