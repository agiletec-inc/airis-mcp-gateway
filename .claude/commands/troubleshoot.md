---
description: Diagnose issues with AIRIS MCP Gateway
allowed-tools: Bash(task*), Bash(docker*), Bash(curl*), Read, Grep
argument-hint: [issue-type]
---

# AIRIS MCP Gateway Troubleshooting

Diagnose and suggest fixes for gateway issues.

## Issue Type: $ARGUMENTS

Common issue types: `startup`, `timeout`, `tools`, `persistence`, `connection`

## Diagnostic Steps

### 1. Container Logs (last 50 lines)
```bash
task docker:logs:tail
```

### 2. Error Patterns
Look for these in logs:
- `Error`, `Exception`, `Failed`
- `timeout`, `connection refused`
- `DNS`, `resolve`

### 3. Process Server Status
```bash
task test:status
```

### 4. Configuration Check
Review @mcp-config.json for:
- Servers with `enabled: true` that should be working
- Environment variables that might be missing
- Profile references that might not resolve

## Known Issues & Fixes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| "Name or service not known" | DNS resolution | Check `dns:` in docker-compose.yml |
| Tools timeout on first call | Cold start | Run `task test:prewarm` to check |
| "Cannot find module" | Missing build | Run `task docker:build:nocache` |
| Data lost on restart | No persistence | Check volume mounts in docker-compose.yml |
| Task not found | Not in devbox | Run `devbox shell` first |

## Output

1. Identified issue(s)
2. Root cause analysis
3. Recommended fix with exact commands (use `task` commands where possible)
