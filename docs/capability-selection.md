# Capability Selection Guide

## Purpose

This repository should not only aggregate tools. It should also preserve the decision rules for **when to use MCP, skills, hooks, subagents, or CLI**.

That guidance is part of the product.

## Short rule

- Use **MCP** for shared external capabilities with structured I/O.
- Use **skills** for reusable workflows and operational know-how.
- Use **hooks** for policy, guardrails, and automation around tool use.
- Use **subagents** for context isolation and parallel research.
- Use **CLI** for deterministic local workflows.

## Use MCP when

Choose MCP if the capability:

- connects to an external API or service
- needs structured inputs and outputs
- should work across multiple clients
- benefits from standard discovery and invocation
- should be centrally managed by AIRIS

Good fits:

- Stripe
- Supabase
- Cloudflare
- GitHub API
- Tavily

## Use skills when

Choose skills if the value is mostly in the workflow, not the transport.

Skills are the right home for:

- step-by-step operating procedures
- domain-specific execution rules
- combining multiple tools into one repeatable playbook
- repository-specific conventions
- prompt engineering with scripts and templates

Good fits:

- "How we investigate flaky CI"
- "How we run a production migration"
- "How we collect product research with approved sources"
- "How we turn a support issue into a bugfix PR"

## Use hooks when

Choose hooks for automatic actions before or after tool execution.

Hooks are the right home for:

- dangerous-command confirmation
- secrets scanning
- audit logging
- formatting or validation after edits
- policy enforcement by workspace or subagent

Hooks should not carry large domain workflows. They should enforce policy and lightweight automation.

## Use subagents when

Choose subagents when you need context separation.

Good fits:

- broad codebase exploration
- background research
- independent review passes
- constrained specialist roles

Subagents are especially useful when research would otherwise pollute the main conversation.

## Use CLI when

Choose CLI for deterministic local workflows with strong existing tooling.

Good fits:

- `gh`
- `git`
- `docker`
- `psql`
- `playwright`
- `pytest`
- `pnpm`

If the tool is already excellent as a command-line interface, do not force it into MCP unless central management or remote access adds clear value.

## Playwright guidance

Default to **CLI + skill**, not MCP.

Why:

- Playwright already has strong local commands
- browser automation often needs host integration
- test execution, trace viewing, and code generation are naturally CLI-shaped

Recommended split:

- CLI for `test`, `codegen`, `show-report`, and traces
- skill for workflow guidance and conventions
- MCP only when live browser control is truly needed as an agent capability

## AIRIS-specific guidance

### Best fits for AIRIS MCP

- remote APIs
- high-value provider integrations
- centrally configured secrets
- reusable capability exposure across Codex, Claude Code, and other clients

### Best fits for `airis-monorepo`

- monorepo commands
- repo-local hooks and guards
- repository operating conventions
- workflow skills for development and release tasks
- host-side automation that is specific to the monorepo

### Best fits for AIRIS docs and skills

- "Which capability should I use?"
- "What is our approved workflow?"
- "How do we safely operate this integration?"
- "When should this stay cold or disabled?"

If the workflow is specifically about working inside the monorepo, prefer documenting it in `airis-monorepo` and let that repo invoke AIRIS where needed.

### Best fits for repo hooks

- validation
- policy checks
- usage logging
- security enforcement

## Decision matrix

| Need | Best home |
|------|-----------|
| Shared API integration | MCP |
| Team workflow guidance | Skill |
| Automatic policy enforcement | Hook |
| Context isolation for research | Subagent |
| Deterministic local command | CLI |
| Large provider with many tools | MCP + toolsets |
| Browser testing workflow | CLI + skill |
| Monorepo workflow automation | `airis-monorepo` |

## Practical examples

### Stripe

- transport: MCP
- exposure: toolsets
- workflow guidance: skill
- safety checks: hooks

### Supabase

- transport: MCP
- exposure: toolsets such as SQL, auth, storage
- migration runbooks: skill
- dangerous write confirmation: hooks

### Playwright

- transport: CLI
- workflow guidance: skill
- optional live browser control: MCP only if justified

### GitHub

- deterministic repo actions: `gh` CLI
- broad reusable API capability: MCP
- review workflow guidance: skill

### Monorepo management

- shared external capability: AIRIS MCP if needed
- repo commands, hooks, guards, skills: `airis-monorepo`
- local workflow policy: `airis-monorepo`

## Repository expectation

AIRIS should ship both:

- capability plumbing
- capability selection knowledge

Without the second, teams will recreate the same routing heuristics in prompts over and over.

But AIRIS should not become the home for all repo workflow logic. Keep the shared capability plane in this repository, and keep monorepo operating logic in `airis-monorepo`.
