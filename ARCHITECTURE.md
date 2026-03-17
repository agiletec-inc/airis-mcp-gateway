# AIRIS Architecture

## Responsibility = Repository = OCI Image

Each repository has ONE responsibility and produces ONE OCI image.

| Repository | Responsibility | Image |
|------------|---------------|-------|
| `airis-mcp-gateway` | MCP routing/proxy + intelligence layer | `ghcr.io/agiletec-inc/airis-mcp-gateway` |
| `mindbase` | Long-term memory storage | `ghcr.io/agiletec-inc/mindbase` |
| `airis-workspace` | Toolchain (monorepo management) | `ghcr.io/agiletec-inc/airis-workspace` |

## airis-mcp-gateway (This Repository)

### Allowed Responsibilities

- MCP server registration and multiplexing
- SSE/JSON-RPC transport proxy
- Process server management (lazy loading, idle kill)
- Schema partitioning for token optimization
- Server enable/disable at runtime
- Pre-implementation confidence assessment (`airis-confidence`)
- Repository structure indexing (`airis-repo-index`)
- MCP tool suggestion from natural language (`airis-suggest`)
- Task-to-tool-chain routing (`airis-route`)
- Prometheus metrics
- Rate limiting and auth (future)
- Audit logging (future)

### Why Schema Partitioning Must Be Here

Schema partitioning **cannot** be moved to a separate agent because:

```
Claude Code
    ↓ tools/list request
Gateway ← Must intercept HERE to reduce tokens
    ↓
MCP servers (return full schemas)
```

- Token optimization must happen at the proxy layer
- No external agent can intercept other servers' responses

### Prohibited

- **NO Orchestration**: PDCA cycles, multi-step workflows
- **NO Intent Detection**: 7-verb intent routing
- **NO PDCA**: Plan-Do-Check-Act loops

## Cross-Repository Communication

Services communicate via **API/MCP only**. No git submodules.

```
Claude Code
    |
    v
airis-mcp-gateway (port 9400)
    |
    +-- Dynamic MCP Layer (airis-find, airis-exec, airis-schema)
    |
    +-- Native Tools (airis-confidence, airis-repo-index, airis-suggest, airis-route)
    |
    +-- MCP proxy --> Docker MCP Gateway --> mindbase, time, etc.
    |
    +-- Process mgmt --> context7, memory, stripe, playwright, etc.
```

## Deployment

### Lite Mode (Default)

Gateway + process-based MCP servers (uvx/npx):

```bash
docker compose up -d
```

### Full Mode

All services as Docker containers:

```bash
docker compose -f infra/compose.yaml --profile full up -d
```

## Adding New Features

### If the feature is routing/proxy/intelligence related:

Add to `airis-mcp-gateway`.

### If the feature involves persistent storage or memory:

Add to `mindbase` and expose via MCP tool.
