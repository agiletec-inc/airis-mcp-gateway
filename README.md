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

```bash
docker compose up -d          # Start
docker compose down           # Stop
docker compose restart api    # Restart API
docker compose logs -f api    # View API logs
docker compose pull && docker compose up -d  # Update
```

## Development

For local development with hot reload:

```bash
# 1. Build MCP servers locally (one-time, or after changes)
cd apps/airis-commands && npm install && npm run build && cd ../..
cd apps/gateway-control && npm install && npm run build && cd ../..

# 2. Start with dev overrides
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 3. Watch logs
docker compose logs -f api
```

**What dev mode provides:**
- Python hot reload (uvicorn `--reload`)
- Source code mounted - edit `apps/api/src/` and changes apply immediately
- Node dist folders mounted - rebuild locally, changes reflect without Docker rebuild

**Workflow:**
1. Edit Python code → auto-reloads
2. Edit TypeScript → run `npm run build` in the app folder → reflected immediately

**Note:** Dev and prod use the same ports (9400). Stop one before starting the other.

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
