---
name: mcp-implementation
description: Use when implementing features that use external libraries or APIs — ensures docs-first approach before writing code
---

# MCP Docs-First Implementation Workflow

Use this workflow when implementing features that involve external libraries or APIs you're not 100% certain about.

## Prerequisites

Gateway instructions handle tool routing. This skill teaches the implementation sequence that avoids wasted effort from wrong assumptions.

## Workflow

### Step 1: Check documentation before coding

Before writing any implementation code:
1. Look up the library/API documentation using Gateway doc tools
2. Find the specific function/method/endpoint you plan to use
3. Check for official examples or sample code

**If official examples exist, use them as your starting point** rather than writing from scratch.

### Step 2: Check existing patterns in the codebase

Use native Grep/Glob tools (not Gateway) to:
1. Search for existing usage of the same library in this project
2. Check import patterns and initialization conventions
3. Look for existing wrappers or utilities

**If the codebase already uses this library, follow the established pattern.**

### Step 3: Implement

With documentation and existing patterns in hand:
1. Write the implementation following official docs and project conventions
2. Handle errors explicitly — no silent fallbacks
3. Keep the implementation minimal — don't add features beyond what's needed

### Step 4: Verify

1. Run tests to confirm the implementation works
2. Check for type errors and lint issues
3. If the change is user-facing, verify in the browser

## Decision Points

| Situation | Action |
|-----------|--------|
| Using a library for the first time | Full workflow: docs → patterns → implement → verify |
| Library already used in codebase | Skip docs, follow existing patterns |
| API call to external service | Always check docs for auth, rate limits, error codes |
| Uncertain about behavior | Check docs first, don't guess |

## Anti-patterns

- Writing code based on memory instead of checking current docs
- Ignoring existing patterns in the codebase
- Adding error handling for scenarios that can't happen
- Over-engineering beyond the task requirements
