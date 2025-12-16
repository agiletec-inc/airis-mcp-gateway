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

Done! You now have access to 60+ tools.

## Default Enabled Servers

| Server | Runner | Mode | Description |
|--------|--------|------|-------------|
| **airis-agent** | uvx | HOT | Confidence check, deep research, repo indexing |
| **context7** | npx | COLD | Library documentation lookup |
| **fetch** | uvx | COLD | Web page fetching as markdown |
| **memory** | npx | HOT | Knowledge graph (entities, relations) |
| **sequential-thinking** | npx | COLD | Step-by-step reasoning |
| **serena** | mcp-remote | COLD | Semantic code retrieval and editing |
| **tavily** | npx | COLD | Web search via Tavily API |
| **playwright** | npx | COLD | Browser automation |
| **magic** | npx | COLD | UI component generation |
| **morphllm** | npx | COLD | Code editing with warpgrep |
| **chrome-devtools** | npx | COLD | Chrome debugging |
| **airis-mcp-gateway-control** | node | HOT | Gateway management tools |
| **airis-commands** | node | HOT | Config and profile management |

**HOT**: Always running, immediate response
**COLD**: Start on-demand, auto-terminate when idle

## Architecture

```
Claude Code / Cursor / Zed
    │
    ▼ SSE (http://localhost:9400/sse)
┌─────────────────────────────────────────────────────────┐
│  FastAPI Hybrid MCP Multiplexer (port 9400)             │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Docker Gateway (9390)                          │    │
│  │  └─ mindbase, time (via catalog)                │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  ProcessManager (Lazy start + idle-kill)        │    │
│  │  ├─ airis-agent (uvx)       HOT                 │    │
│  │  ├─ memory (npx)            HOT                 │    │
│  │  ├─ gateway-control (node)  HOT                 │    │
│  │  ├─ airis-commands (node)   HOT                 │    │
│  │  ├─ context7 (npx)          COLD                │    │
│  │  ├─ fetch (uvx)             COLD                │    │
│  │  ├─ sequential-thinking     COLD                │    │
│  │  ├─ serena (mcp-remote)     COLD                │    │
│  │  ├─ tavily (npx)            COLD                │    │
│  │  ├─ playwright (npx)        COLD                │    │
│  │  ├─ magic (npx)             COLD                │    │
│  │  ├─ morphllm (npx)          COLD                │    │
│  │  └─ chrome-devtools (npx)   COLD                │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  PostgreSQL + pgvector (mindbase storage)       │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Configuration

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
| `/metrics` | Prometheus metrics |

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

## Related Projects

| Project | Description |
|---------|-------------|
| [airis-agent](https://github.com/agiletec-inc/airis-agent) | Intelligence layer - confidence checks, deep research |
| [mindbase](https://github.com/agiletec-inc/mindbase) | Cross-session semantic memory |
| [airis-workspace](https://github.com/agiletec-inc/airis-workspace) | Docker-first monorepo manager |

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
