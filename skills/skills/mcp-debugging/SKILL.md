---
name: mcp-debugging
description: Use when debugging issues that involve external services, database state, or API behavior — complements superpowers:systematic-debugging with MCP tool usage
---

# MCP-Assisted Debugging Workflow

Use this workflow when debugging issues that may involve external services, database state, or API behavior. This complements superpowers' systematic-debugging skill — use that first for root cause analysis methodology, then use this skill for MCP-specific investigation tools.

## Prerequisites

If superpowers:systematic-debugging applies, invoke it first. This skill adds MCP-specific investigation techniques on top of that methodology.

## Workflow

### Step 1: Gather observable state

Use available Gateway tools to collect evidence:
1. **Logs**: Check application/service logs for errors and stack traces
2. **Database state**: Query relevant tables to inspect current data
3. **API responses**: If the issue involves an external API, check recent responses

Collect first, hypothesize second.

### Step 2: Narrow the scope

Based on evidence from Step 1:
- Is the issue in the data? (wrong/missing/corrupted records)
- Is the issue in the API? (auth failure, rate limit, schema change)
- Is the issue in the code? (logic error, race condition)

### Step 3: Investigate with targeted queries

| If the issue is in... | Investigation approach |
|-----------------------|----------------------|
| Database | Schema check → query affected tables → trace data flow |
| External API | Check docs for changes → test with minimal request → verify auth |
| Application logs | Filter for error patterns → trace request flow → check timestamps |
| Unknown | Search web for the specific error message |

### Step 4: Verify the fix

After implementing a fix:
1. Reproduce the original issue conditions
2. Confirm the fix resolves the problem
3. Check that no new issues were introduced (run tests)
4. Verify in the actual environment (browser, logs, database)

## When to use this vs systematic-debugging

- **systematic-debugging**: Root cause methodology — how to think about bugs
- **mcp-debugging**: Investigation tools — how to gather evidence using MCP tools
- **Use both together**: systematic-debugging for methodology, this skill for tooling

## Anti-patterns

- Guessing at the cause without checking logs or data first
- Fixing symptoms instead of root causes
- Not verifying the fix in the actual environment
- Skipping the database state check when data is involved
