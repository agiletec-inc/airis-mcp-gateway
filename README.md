# AIRIS MCP Gateway

<p align="center">
  <img src="./assets/demo.gif" width="720" alt="AIRIS MCP Gateway Demo" />
</p>

One command to add 60+ AI tools to Claude Code. No config, no setup, just works.

## Quick Start

```bash
# 1. Clone and start
git clone https://github.com/agiletec-inc/airis-mcp-gateway.git
cd airis-mcp-gateway
docker compose up -d

# 2. Register with Claude Code
claude mcp add --scope user --transport sse airis-mcp-gateway http://localhost:9400/sse
```

Done! You now have access to 60+ tools via **Dynamic MCP** - a token-efficient way to access all tools.

## Dynamic MCP (Default)

Instead of exposing all 60+ tools directly (which bloats context), Dynamic MCP exposes 7 meta-tools:

| Meta-Tool | Description |
|-----------|-------------|
| `airis-find` | Search for tools by name, description, or server |
| `airis-exec` | Execute any tool by `server:tool_name` |
| `airis-schema` | Get full input schema for a tool |
| `airis-confidence` | Pre-implementation confidence check |
| `airis-repo-index` | Generate repository structure overview |
| `airis-suggest` | Tool recommendations from natural language |
| `airis-route` | Route task to optimal tool chain |

External tools (HOT and COLD) are accessed via `airis-exec`. This follows the [Lasso MCP Gateway](https://github.com/lasso-security/mcp-gateway) pattern for maximum token efficiency.

### How It Works

```
User: "Save this note about the meeting"

Claude: [calls airis-find query="memory"]
→ memory:create_entities, memory:search_entities, ...

Claude: [calls airis-schema tool="memory:create_entities"]
→ { "entities": [...], "relations": [...] }

Claude: [calls airis-exec tool="memory:create_entities" arguments={...}]
→ Done!
```

### Auto-Enable on Demand

LLM can discover ALL servers (including disabled ones) via `airis-find`:

```
Claude: [calls airis-find query="stripe"]
→ stripe (cold, disabled): 50 tools

Claude: [calls airis-exec tool="stripe:create_customer" arguments={...}]
→ Server auto-enabled, tool executed!
```

When `airis-exec` is called on a disabled server:
1. Server is automatically enabled
2. Tools are loaded
3. Tool is executed
4. No manual enable/disable required

### Token Savings

```
Traditional: 60+ tools × ~700 tokens = ~42,000 tokens
Dynamic MCP: 7 meta-tools × ~200 tokens = ~1,400 tokens (97% reduction)
```

This matches [Anthropic's recommendation](https://www.anthropic.com/engineering/code-execution-with-mcp) for progressive disclosure - only load tool definitions when needed.

### Disable Dynamic MCP

If you prefer all tools exposed directly (legacy mode):

```bash
DYNAMIC_MCP=false docker compose up -d
```

## Server List

### Enabled by Default

| Server | Runner | Mode | Description |
|--------|--------|------|-------------|
| **airis-mcp-gateway-control** | node | HOT | Gateway management tools |
| **airis-commands** | node | HOT | Config and profile management |
| **context7** | npx | COLD | Library documentation lookup |
| **fetch** | uvx | COLD | Web page fetching as markdown |
| **memory** | npx | COLD | Knowledge graph (entities, relations) |
| **sequential-thinking** | npx | COLD | Step-by-step reasoning |
| **serena** | mcp-remote | COLD | Semantic code retrieval and editing |
| **tavily** | npx | COLD | Web search via Tavily API |
| **playwright** | npx | COLD | Browser automation |
| **magic** | npx | COLD | UI component generation |
| **morphllm** | npx | COLD | Code editing with warpgrep |
| **chrome-devtools** | npx | COLD | Chrome debugging |
| **supabase** | npx | COLD | Supabase database management |
| **stripe** | npx | COLD | Stripe payments API |

### Disabled by Default (Auto-Enable via airis-exec)

| Server | Runner | Description |
|--------|--------|-------------|
| **twilio** | npx | Twilio voice/SMS API |
| **cloudflare** | npx | Cloudflare management |
| **github** | npx | GitHub API |
| **postgres** | npx | Direct PostgreSQL access |
| **filesystem** | npx | File system operations |
| **git** | npx | Git operations |
| **time** | npx | Time utilities |

**HOT**: Always running, immediate response
**COLD**: Start on-demand, auto-terminate when idle

> Disabled servers are discoverable via `airis-find` and automatically enabled when you call `airis-exec`.

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
│  │  ├─ airis-find       (discover all servers/tools)│    │
│  │  ├─ airis-exec       (execute + auto-enable)    │    │
│  │  ├─ airis-schema     (get tool input schema)    │    │
│  │  ├─ airis-confidence (pre-impl confidence)      │    │
│  │  ├─ airis-repo-index (repo structure overview)  │    │
│  │  ├─ airis-suggest    (NL tool recommendations)  │    │
│  │  └─ airis-route      (task→tool chain routing)  │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  ProcessManager (Lazy start + idle-kill)        │    │
│  │  ├─ gateway-control (node)  HOT                 │    │
│  │  ├─ airis-commands (node)   HOT                 │    │
│  │  ├─ memory (npx)            COLD                │    │
│  │  ├─ context7 (npx)          COLD                │    │
│  │  ├─ serena (mcp-remote)     COLD                │    │
│  │  ├─ tavily (npx)            COLD                │    │
│  │  ├─ playwright (npx)        COLD                │    │
│  │  ├─ supabase (npx)          COLD                │    │
│  │  ├─ stripe (npx)            COLD                │    │
│  │  └─ ... (20+ more servers)                      │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Docker Gateway (9390) - mindbase, etc.         │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DYNAMIC_MCP` | `true` | Enable Dynamic MCP (3 meta-tools vs 60+ tools) |
| `TOOL_CALL_TIMEOUT` | `90` | Fail-safe timeout (seconds) for MCP tool calls |
| `AIRIS_API_KEY` | *(none)* | API key for authentication (disabled if not set) |

#### API Key Authentication

Optional bearer token authentication. Disabled by default (open access).

```bash
# Generate a secure API key
openssl rand -hex 32

# Set in .env or docker-compose.yml
AIRIS_API_KEY=your-generated-key
```

When enabled, all requests require the `Authorization` header:

```bash
curl -H "Authorization: Bearer your-api-key" http://localhost:9400/health
```

**Excluded endpoints** (no auth required): `/health`, `/ready`, `/`

#### Fail-Safe Timeout

The gateway includes a configurable fail-safe timeout to prevent Claude Code from hanging indefinitely on frozen MCP tool calls:

```bash
# In docker-compose.yml or .env
TOOL_CALL_TIMEOUT=90  # Default: 90 seconds
```

This timeout applies to both ProcessManager tool calls and Docker Gateway proxy requests.

### Per-Server TTL Settings

Fine-tune idle timeout behavior per server in `mcp-config.json`:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-playwright"],
      "enabled": true,
      "mode": "hot",
      "idle_timeout": 900,
      "min_ttl": 300,
      "max_ttl": 1800
    }
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `idle_timeout` | `120` | Seconds before idle server is terminated |
| `min_ttl` | `60` | Minimum time server stays alive after start |
| `max_ttl` | `3600` | Maximum time server can run (hard limit) |

**HOT servers** benefit from longer `idle_timeout` (e.g., 900s) to avoid cold starts.
**COLD servers** use shorter timeouts (e.g., 300s) to free resources.

### Enable/Disable Servers

Edit `mcp-config.json`:

```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "enabled": true,
      "mode": "hot"
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"],
      "enabled": true,
      "mode": "cold"
    }
  }
}
```

Then restart:

```bash
docker compose restart api
```

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/sse` | SSE endpoint for Claude Code |
| `/health` | Health check |
| `/api/tools/combined` | All tools from all sources |
| `/api/tools/status` | Server status overview |
| `/process/servers` | List process servers |
| `/metrics` | Prometheus metrics (see below) |

### Prometheus Metrics

The `/metrics` endpoint exposes Prometheus-compatible metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `mcp_active_processes` | gauge | Number of running MCP servers |
| `mcp_stopped_processes` | gauge | Number of stopped MCP servers |
| `mcp_total_processes` | gauge | Total configured MCP servers |
| `mcp_server_enabled{server}` | gauge | Server enabled (1) or disabled (0) |
| `mcp_server_tools{server}` | gauge | Number of tools per server |
| `mcp_server_uptime_seconds{server}` | gauge | Server uptime in seconds |
| `mcp_server_spawn_total{server}` | counter | Total process spawns (restarts) |
| `mcp_server_calls_total{server}` | counter | Total tool calls |
| `mcp_server_latency_p50_ms{server}` | gauge | 50th percentile latency |
| `mcp_server_latency_p95_ms{server}` | gauge | 95th percentile latency |
| `mcp_server_latency_p99_ms{server}` | gauge | 99th percentile latency |

Example scrape config for Prometheus:

```yaml
scrape_configs:
  - job_name: 'airis-mcp-gateway'
    static_configs:
      - targets: ['localhost:9400']
```

## Commands

All commands are managed via [go-task](https://taskfile.dev). Enter the development shell first:

```bash
devbox shell              # Enter dev environment (or use direnv)
task --list-all           # Show all available tasks
```

### Common Tasks

```bash
task docker:up            # Start the stack
task docker:down          # Stop the stack
task docker:logs          # Follow API logs
task docker:restart       # Restart API container
task test:e2e             # Run end-to-end tests
task status               # Quick health check
```

### All Task Namespaces

| Namespace | Description |
|-----------|-------------|
| `docker:*` | Container lifecycle (up, down, logs, shell, clean) |
| `dev:*` | Development mode with hot reload |
| `build:*` | MCP server builds (pnpm/esbuild) |
| `test:*` | Health checks and e2e tests |

## Development

### Prerequisites

Install [Devbox](https://www.jetify.com/devbox) for a reproducible dev environment:

```bash
curl -fsSL https://get.jetify.com/devbox | bash
```

### Why Devbox + go-task?

This project uses Devbox and go-task to solve common development pain points:

**The Problem:**
- "It works on my machine" - Different Node/Python versions cause subtle bugs
- Onboarding friction - New contributors spend hours installing dependencies
- Command sprawl - Scattered scripts, docker commands, and manual steps
- AI pairing issues - Claude Code struggles with inconsistent environments

**The Solution:**

| Tool | What it does | Why it matters |
|------|--------------|----------------|
| **Devbox** | Isolated, reproducible dev environment | Everyone gets identical tools (Node 22, Python 3.12, etc.) without polluting their system. Works on macOS, Linux, and WSL. |
| **go-task** | Task runner with namespaced commands | One way to do things: `task docker:up` instead of memorizing docker-compose flags. Self-documenting via `task --list-all`. |

**Benefits for AI-assisted development:**
- Claude Code can reliably run `task test:e2e` knowing it will work
- Consistent paths via `REPO_ROOT` prevent path-related errors
- Namespaced tasks are discoverable and predictable

**No Devbox? No problem:**
```bash
# Manual alternative (you manage your own tool versions)
docker compose up -d
curl http://localhost:9400/health
```

### Dev Workflow

```bash
devbox shell              # Enter dev environment
task dev:up               # Start with hot reload
task docker:logs          # Watch for changes
```

**What dev mode provides:**
- Python hot reload (uvicorn `--reload`)
- Source code mounted - edit `apps/api/src/` and changes apply immediately
- Node dist folders mounted - rebuild locally, changes reflect without Docker rebuild

**TypeScript changes:**
```bash
task build:mcp            # Rebuild MCP servers
# Or use watch mode:
task dev:watch            # Auto-rebuild on file changes
```

**Note:** Dev and prod use the same ports (9400). Stop one before starting the other.

## Claude Code Integration

This repo includes built-in slash commands for Claude Code users. When you open this project in Claude Code, you get instant access to testing and troubleshooting tools.

### Available Commands

| Command | Description |
|---------|-------------|
| `/test` | End-to-end test of gateway health, tools, and pre-warming |
| `/test persistence` | Full test including data persistence across restart |
| `/status` | Quick status check of containers, API, and servers |
| `/troubleshoot [issue]` | Diagnose issues (startup, timeout, tools, connection) |

### Usage

```bash
# In Claude Code TUI, just type:
/test                    # Run full test suite
/status                  # Quick health check
/troubleshoot timeout    # Debug timeout issues
```

### How It Works

Commands live in `.claude/commands/` and become prompts that Claude executes with appropriate tool permissions. This means:

- **Zero setup** - Commands are available as soon as you open the repo
- **Context-aware** - Commands reference project files and config automatically
- **Safe** - Tool permissions are scoped (only docker, curl, MCP tools)

### Creating Custom Commands

Add a markdown file to `.claude/commands/`:

```markdown
# .claude/commands/my-command.md
---
description: What this command does
allowed-tools: Bash(docker*), mcp__airis-mcp-gateway__*
---

Your prompt here. Use $ARGUMENTS for user input.
```

## Verify Installation

```bash
# Check health
curl http://localhost:9400/health

# List all tools
curl http://localhost:9400/api/tools/combined | jq '.tools_count'

# Check server status
curl http://localhost:9400/api/tools/status | jq '.servers[] | {name, status}'
```

## Adding New Servers

### Python MCP Server (uvx)

```json
{
  "my-server": {
    "command": "uvx",
    "args": ["my-mcp-server"],
    "enabled": true,
    "mode": "cold"
  }
}
```

### Node.js MCP Server (npx)

```json
{
  "my-server": {
    "command": "npx",
    "args": ["-y", "@org/my-mcp-server"],
    "enabled": true,
    "mode": "cold"
  }
}
```

## Ecosystem

| Project | Description |
|---------|-------------|
| [airis-monorepo](https://github.com/agiletec-inc/airis-monorepo) | `airis` CLI - Docker-first monorepo manager |
| [mindbase](https://github.com/agiletec-inc/mindbase) | Cross-session semantic memory |
| ~~[airis-agent](https://github.com/agiletec-inc/airis-agent)~~ | Archived - intelligence layer integrated into this gateway |

## Troubleshooting

### Check Status

```bash
docker compose ps
docker compose logs --tail 50 api
curl http://localhost:9400/metrics
```

### Reset

```bash
docker compose down -v
docker compose up -d
```

### Process Server Issues

```bash
# Check specific server status
curl http://localhost:9400/process/servers/memory | jq

# View server logs
docker compose logs api | grep -i memory
```

## License

MIT
