---
description: Decide whether to use AIRIS MCP, CLI, hooks, or skills
allowed-tools: Read, Grep, Bash(rg:*), mcp__airis-mcp-gateway__*
---

Route the task using AIRIS best practices.

Use this order:
1. Identify whether the task is shared external capability, local deterministic workflow, or workflow guidance.
2. Choose MCP for shared APIs and structured I/O.
3. Choose CLI for deterministic local execution such as Playwright, git, docker, and test runners.
4. Choose hooks or skills when the value is guardrails or reusable workflow steps.
5. Explain the chosen route briefly before doing the work.
