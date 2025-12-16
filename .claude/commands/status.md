---
description: Quick status check of AIRIS MCP Gateway stack
allowed-tools: Bash(docker*), Bash(curl*)
---

# AIRIS MCP Gateway Status

Provide a quick status overview of the gateway stack.

## Checks to Run

1. **Docker Containers**
```bash
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
```

2. **API Health**
```bash
curl -s http://localhost:9400/health | jq .
```

3. **Server Status**
```bash
curl -s http://localhost:9400/api/tools/status | jq '.servers[] | {name, status, tools_count}'
```

4. **Tool Count**
```bash
curl -s http://localhost:9400/api/tools/combined | jq '.tools_count'
```

## Output Format

Summarize in a compact status block:
- Container: running/stopped
- API: healthy/unhealthy
- Servers: X ready, Y stopped
- Tools: N total
