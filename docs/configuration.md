# Configuration

## Global Registry Policy

AIRIS keeps a single user-level MCP registry at `~/.airis/mcp/registry.json`.

- Repository-local `mcp.json` files are forbidden after migration.
- Import existing `mcp.json` files into the global registry, then back them up and remove them.
- `airis-gateway doctor` fails if repo-local `mcp.json` files still exist.
- `airis-gateway init --apply` deploys AIRIS best-practice assets to Codex, Claude Code, and Gemini.
- Codex and Gemini can be managed automatically by AIRIS.
- Claude Desktop is intentionally left unmanaged and is never modified automatically.

Recommended workflow:

```bash
airis-gateway init ~/github
airis-gateway init ~/github --apply
airis-gateway doctor ~/github
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DYNAMIC_MCP` | `true` | Enable Dynamic MCP (7 meta-tools vs 60+ tools) |
| `TOOL_CALL_TIMEOUT` | `90` | Fail-safe timeout (seconds) for MCP tool calls |
| `AIRIS_API_KEY` | *(none)* | API key for authentication (disabled if not set) |

### API Key Authentication

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

### Fail-Safe Timeout

The gateway includes a configurable fail-safe timeout to prevent Claude Code from hanging indefinitely on frozen MCP tool calls:

```bash
# In docker-compose.yml or .env
TOOL_CALL_TIMEOUT=90  # Default: 90 seconds
```

This timeout applies to both ProcessManager tool calls and Docker Gateway proxy requests.

## Per-Server TTL Settings

Fine-tune idle timeout behavior per server in `mcp-config.json`:

```json
{
  "mcpServers": {
    "tavily": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.tavily.com/mcp/?tavilyApiKey=${TAVILY_API_KEY}"],
      "enabled": true,
      "mode": "cold",
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

## Enable/Disable Servers

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

### Disable Dynamic MCP

If you prefer all tools exposed directly (legacy mode):

```bash
DYNAMIC_MCP=false docker compose up -d
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/sse` | SSE endpoint for Claude Code |
| `/health` | Health check |
| `/api/tools/combined` | All tools from all sources |
| `/api/tools/status` | Server status overview |
| `/process/servers` | List process servers |
| `/metrics` | Prometheus metrics (see [Deployment Guide](../DEPLOYMENT.md#monitoring)) |

## Prometheus Metrics

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
