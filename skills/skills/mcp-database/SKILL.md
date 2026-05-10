---
name: mcp-database
description: Use when querying, modifying, or investigating database state — enforces schema-first approach and mutation safety
---

# MCP Database Workflow

Use this workflow when you need to query, investigate, or modify database state.

## Prerequisites

Gateway instructions already tell you WHICH tools handle database operations. This skill teaches the safe workflow for using them.

## Workflow

### Step 1: Understand the schema

Before writing any query:
1. List available tables to understand the data model
2. Describe the specific table(s) you'll be working with
3. Note column types, constraints, and relationships

**Never write a query against a table you haven't inspected.**

### Step 2: Read before write

Always run a SELECT to understand current state before any mutation:
- Check what data exists
- Verify your WHERE clause matches the expected rows
- Confirm row counts

### Step 3: Execute with appropriate caution

| Operation | Caution Level |
|-----------|---------------|
| SELECT | Auto-execute OK |
| INSERT (new data) | Confirm with user — describe what will be inserted |
| UPDATE | Confirm with user — show the SELECT of affected rows first |
| DELETE | Always confirm — show affected rows and ask explicitly |
| DDL (ALTER, DROP) | Always confirm — these are irreversible |

### Step 4: Verify after mutation

After any INSERT/UPDATE/DELETE:
1. Run a SELECT to confirm the change took effect
2. Check row counts match expectations
3. Report the before/after state to the user

## Decision Points

| Situation | Action |
|-----------|--------|
| Need to understand data model | List tables → describe relevant tables |
| Simple data lookup | SELECT directly (schema check optional for known tables) |
| Data modification needed | SELECT first → confirm with user → execute → verify |
| Debugging a data issue | Schema check → SELECT to inspect state → trace the problem |
| Need to check logs | Use the Gateway's log retrieval tools |

## Anti-patterns

- Writing queries without checking the schema first
- Running UPDATE/DELETE without previewing affected rows
- Not verifying mutations after execution
- Assuming table structure from memory (schemas change)
