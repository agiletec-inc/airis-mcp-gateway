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

## Pull Request Checklist

- [ ] Does this change add orchestration logic? If yes, reconsider the design.
- [ ] Does this change add storage logic? If yes, submit to `mindbase` instead.
- [ ] Is the change routing/proxy/intelligence focused?
- [ ] Are tests included?
- [ ] Is documentation updated?

## Development

```bash
# Start services
docker compose up -d

# View logs
docker compose logs -f api

# Run tests
cd apps/api && pytest tests/

# Restart after config changes
docker compose restart api
```

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
