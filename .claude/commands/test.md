---
description: End-to-end test of AIRIS MCP Gateway - health, tools, persistence
allowed-tools: Bash(task*), Bash(docker*), Bash(curl*), mcp__airis-mcp-gateway__*
---

# AIRIS MCP Gateway End-to-End Test

Run a comprehensive end-to-end test of the AIRIS MCP Gateway.

## Pre-flight Checks

Container status: !`task docker:ps 2>/dev/null || docker compose ps 2>/dev/null || echo "Stack not running"`

## Test Sequence

Execute these tests in order:

### 1. Gateway Health
- Call `mcp__airis-mcp-gateway__gateway_health` to verify the gateway is healthy
- Confirm status is "healthy" and at least some servers are "ready"

### 2. HOT Server Pre-warming
- Check pre-warm status: `task test:prewarm`
- Verify all 4 HOT servers (airis-agent, memory, airis-mcp-gateway-control, airis-commands) pre-warmed

### 3. Tool Functionality
Test tools from different servers:
- **Time server**: Call `mcp__airis-mcp-gateway__get_current_time` with timezone "UTC"
- **Memory server**: Call `mcp__airis-mcp-gateway__read_graph` to read knowledge graph
- **AIRIS Agent**: Call `mcp__airis-mcp-gateway__airis_confidence_check` with task "test"

### 4. Data Persistence (optional)
If $ARGUMENTS contains "persistence":
- Create a test entity with `mcp__airis-mcp-gateway__create_entities`
- Restart container: `task docker:restart`
- Wait 10 seconds for pre-warm
- Verify entity still exists with `mcp__airis-mcp-gateway__read_graph`
- Clean up test entity with `mcp__airis-mcp-gateway__delete_entities`

## Output

Provide a summary table:

| Test | Status | Details |
|------|--------|---------|
| Gateway Health | | |
| Pre-warming | | |
| Time Tool | | |
| Memory Tool | | |
| AIRIS Agent | | |
| Persistence | | (if tested) |

Report any failures with actionable troubleshooting steps.
