# Migration Guide

## Upgrading to Dynamic MCP (v2.x)

### What Changed

Dynamic MCP is now the default mode. Instead of exposing 60+ tools directly, the gateway exposes a small control plane and activates native tools on demand:

| Old | New |
|-----|-----|
| 60+ tools in `tools/list` | small control plane + activated native tools |
| Manual server enable/disable | activation-driven native tool exposure |
| All servers visible to LLM | toolsets exposed only when needed |

### Migration Steps

#### 1. Update Gateway

```bash
docker compose pull
docker compose up -d
```

#### 2. Update Tool Usage (if using directly)

If you were calling tools directly:

```python
# Old
result = mcp.call("memory:create_entities", {...})

# New — no activation step: calling the tool auto-discovers and
# auto-enables its COLD server on first use
result = mcp.call("memory:create_entities", {...})
```

#### 3. Discover or activate capabilities

Use `airis-find` only when the needed tool or toolset is unclear:

```python
# Optional fallback search
mcp.call("airis-find", {"query": "memory"})
```

If you already know the tool, call it directly (or via `airis-exec`) —
the gateway auto-enables the COLD server on first call:

```python
mcp.call("airis-exec", {"tool": "stripe:create_customer", "arguments": {...}})
```

### Reverting to Legacy Mode

If you need all tools exposed directly:

```bash
DYNAMIC_MCP=false docker compose up -d
```

### API Compatibility

The SSE endpoint remains the same:
- `GET /sse` - SSE stream
- `POST /sse?sessionid=X` - JSON-RPC requests

### Troubleshooting

#### "Tool not found"

Call the tool by its full `server:tool` name via `airis-exec` — COLD
servers auto-enable on first call. If the name is unknown, search first:

```
airis-find query="<capability>"
airis-exec tool="provider:tool_name" arguments={...}
```

#### Server not starting

Use `airis-find` only if you do not know which provider or toolset you need:

```
airis-find query="your_task"
```

If a provider is policy-disabled or missing credentials, activation will still fail until that is fixed.

#### Old endpoints return 404

The following endpoints have been removed:
- `POST /do`
- `POST /detect`
- `POST /route`
- `GET /capabilities`

Use Dynamic MCP meta-tools instead.

## Migrating Away from Repo-Local `mcp.json`

AIRIS now expects a single global MCP registry at `~/.airis/mcp/registry.json`.
Repository-local `mcp.json` files should be treated as migration input only, not ongoing configuration.

Recommended steps:

```bash
airis-mcp-gateway init ~/github
airis-mcp-gateway import ~/github --apply
airis-mcp-gateway clean ~/github
airis-mcp-gateway doctor ~/github
```

Notes:
- `import` absorbs existing repo-local server definitions into the global registry.
- `clean` creates a backup before deleting each imported `mcp.json`.
- `doctor` fails if repo-local `mcp.json` files still exist.
- AIRIS can manage Codex automatically, but it does not modify Claude Desktop config.

## Changelog

### v2.0 - Dynamic MCP

- Added a small control plane for activation and schema lookup
- Native tools exposed on demand after activation
- Strong reduction in initial context size
- Tool discovery retained as optional fallback, not mandatory flow

### v1.x - Legacy

- All tools exposed directly
- Manual server management required
- Higher context usage
