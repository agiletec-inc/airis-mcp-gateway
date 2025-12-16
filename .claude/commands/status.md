---
description: Quick status check of AIRIS MCP Gateway stack
allowed-tools: Bash(task*), Bash(docker*), Bash(curl*)
---

# AIRIS MCP Gateway Status

Provide a quick status overview of the gateway stack.

## Checks to Run

1. **Docker Containers**
```bash
task docker:ps
```

2. **API Health**
```bash
task test:health
```

3. **Server Status**
```bash
task test:status
```

4. **Tool Count**
```bash
task test:tools:count
```

## Output Format

Summarize in a compact status block:
- Container: running/stopped
- API: healthy/unhealthy
- Servers: X ready, Y stopped
- Tools: N total
