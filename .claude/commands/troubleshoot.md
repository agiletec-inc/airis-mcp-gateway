---
description: Diagnose issues with AIRIS MCP Gateway
allowed-tools: Bash(docker*), Bash(curl*), Read, Grep
argument-hint: [issue-type]
---

# AIRIS MCP Gateway Troubleshooting

Diagnose and suggest fixes for gateway issues.

## Issue Type: $ARGUMENTS

Common issue types: `startup`, `timeout`, `tools`, `persistence`, `connection`

## Diagnostic Steps

### 1. Container Logs (last 50 lines)
```bash
docker compose logs --tail 50 api 2>&1
```

### 2. Error Patterns
Look for these in logs:
- `Error`, `Exception`, `Failed`
- `timeout`, `connection refused`
- `DNS`, `resolve`

### 3. Process Server Status
```bash
curl -s http://localhost:9400/process/servers | jq '.[] | {name, status, error}'
```

### 4. Configuration Check
Review @mcp-config.json for:
- Servers with `enabled: true` that should be working
- Environment variables that might be missing
- Profile references that might not resolve

## Known Issues & Fixes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| "Name or service not known" | DNS resolution | Add `dns: [8.8.8.8]` to docker-compose.yml |
| Tools timeout on first call | Cold start | Check pre-warm logs, verify HOT mode |
| "Cannot find module" | Missing build | Rebuild with `docker compose build --no-cache` |
| Data lost on restart | No persistence | Check volume mounts in docker-compose.yml |

## Output

1. Identified issue(s)
2. Root cause analysis
3. Recommended fix with exact commands
