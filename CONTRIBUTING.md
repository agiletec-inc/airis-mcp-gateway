# Contributing to airis-mcp-gateway

## Repository Scope

This repository handles **MCP routing/proxy and intelligence layer**. Before contributing, read [ARCHITECTURE.md](./ARCHITECTURE.md).

## What Belongs Here

- MCP transport (SSE, JSON-RPC, stdio)
- Server lifecycle management (start, stop, health check)
- Request routing and proxying
- Schema partitioning and token optimization
- Pre-implementation confidence checks
- Repository structure indexing
- Tool suggestion from natural language
- Task-to-tool-chain routing
- Metrics and observability
- Rate limiting and authentication

## What Does NOT Belong Here

| Feature | Correct Repository |
|---------|-------------------|
| Orchestration (PDCA) | Not supported (use Claude Code's built-in planning) |
| Intent detection | Not supported |
| Memory storage | `mindbase` |
| Graph relationships | `mindbase` |

## Prerequisites

Install [Devbox](https://www.jetify.com/devbox) for a reproducible dev environment:

```bash
curl -fsSL https://get.jetify.com/devbox | bash
```

### Why Devbox + go-task?

| Tool | What it does | Why it matters |
|------|--------------|----------------|
| **Devbox** | Isolated, reproducible dev environment | Everyone gets identical tools (Node 22, Python 3.12, etc.) without polluting their system. Works on macOS, Linux, and WSL. |
| **go-task** | Task runner with namespaced commands | One way to do things: `task docker:up` instead of memorizing docker-compose flags. Self-documenting via `task --list-all`. |

**No Devbox? No problem:**
```bash
# Manual alternative (you manage your own tool versions)
docker compose up -d
curl http://localhost:9400/health
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

### Task Namespaces

| Namespace | Description |
|-----------|-------------|
| `docker:*` | Container lifecycle (up, down, logs, shell, clean) |
| `dev:*` | Development mode with hot reload |
| `build:*` | MCP server builds (pnpm/esbuild) |
| `test:*` | Health checks and e2e tests |

## Dev Workflow

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

See [Configuration Guide](./docs/configuration.md) for TTL settings and advanced options.

## Pull Request Checklist

- [ ] Does this change add orchestration logic? If yes, reconsider the design.
- [ ] Does this change add storage logic? If yes, submit to `mindbase` instead.
- [ ] Is the change routing/proxy/intelligence focused?
- [ ] Are tests included?
- [ ] Is documentation updated?

## Versioning

This project uses a **Single Source of Truth (SoT)** for versioning to avoid drift across multiple languages and packages.

1.  **Truth Source**: The root `VERSION` file (e.g., `1.1.0`).
2.  **Synchronization**: All sub-packages (`apps/api/pyproject.toml`, `apps/*/package.json`) must be kept in sync with the root `VERSION` file.
3.  **Release Trigger**: Releases are managed by GitHub Actions based on Git tags (`v*`).

**To bump the version:**
1.  Update the root `VERSION` file.
2.  Update `version` in `apps/api/pyproject.toml`.
3.  Update `version` in `apps/*/package.json`.
4.  Commit with a prefix (e.g., `feat:`, `fix:`) to trigger the appropriate auto-bump in the CI/CD pipeline.

---

## Commit Convention

```
<type>: <description>

Types:
- feat: New feature
- fix: Bug fix
- refactor: Code restructuring
- docs: Documentation
- test: Tests
- chore: Maintenance
```
