---
description: AIRIS workflow for research-before-implementation
allowed-tools: Read, Grep, Glob, Bash(rg:*), Bash(find:*), Bash(git status:*), mcp__airis-mcp-gateway__*
---

Inspect the current codebase before editing.

Rules:
- Summarize the existing implementation first.
- If the task depends on a library or API, use AIRIS documentation lookup before changing code.
- If the work is browser testing, prefer Playwright CLI guidance instead of MCP.
- Only move to implementation after you can name the target files, public interfaces, and acceptance checks.
