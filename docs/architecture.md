# Architecture

Single source of truth for the gateway's design — both what ships today and the
direction it is evolving toward. The phased plan for getting from one to the other
lives in [toolset-roadmap.md](./toolset-roadmap.md).

- [Repository responsibility](#repository-responsibility) — what this repo owns
- [Current architecture](#current-architecture) — Dynamic MCP as shipped
- [The problem it solves](#the-problem-it-solves) — tool bloat
- [Target direction](#target-direction) — toolset-centric capability gateway
- [Design principles](#design-principles)
- [Cross-repository communication](#cross-repository-communication)

---

## Repository responsibility

Each repository has ONE responsibility and produces ONE OCI image.

| Repository | Responsibility | Image |
|------------|---------------|-------|
| `airis-mcp-gateway` | MCP routing/proxy + intelligence layer | `ghcr.io/agiletec-inc/airis-mcp-gateway` |
| `mindbase` | Long-term memory storage | `ghcr.io/agiletec-inc/mindbase` |

### This repository owns

- MCP server registration and multiplexing
- SSE / JSON-RPC transport proxy
- Process server management (lazy loading, idle kill)
- Schema partitioning for token optimization
- Capability exposure policy for MCP providers
- Toolset activation and tool discovery for MCP-backed capabilities
- Server enable/disable at runtime
- Pre-implementation confidence assessment (`airis-confidence`)
- Repository structure indexing (`airis-repo-index`)
- MCP tool suggestion from natural language (`airis-suggest`)
- Task-to-tool-chain routing (`airis-route`)
- Prometheus metrics

### This repository does NOT own

- **Orchestration** — PDCA cycles, multi-step workflows
- **Intent detection** — verb-based intent routing
- Repo-local commands, hooks, guards, skills (those belong in the consuming monorepo)

### Why schema partitioning must live here

```
Claude Code
    ↓ tools/list request
Gateway ← must intercept HERE to reduce tokens
    ↓
MCP servers (return full schemas)
```

Token optimization has to happen at the proxy layer — no external agent can intercept
another server's responses.

---

## Current architecture

Dynamic MCP keeps the initial tool surface small while still allowing direct calls to
native MCP tools. As shipped today (`DYNAMIC_MCP=true`, the default) the control plane
exposes **4 meta-tools**, plus — when `COLD_TOOLS_IN_LIST=true` (also the default) —
every discoverable COLD server's indexed tools with a lazy stub schema
(`{"type":"object"}`) sitting directly in `tools/list`, instead of only the older
meta-tool-only surface:

| Tool | Purpose |
|------|---------|
| `airis-find` | Discover tools across server/tool metadata (optional discovery aid) |
| `airis-schema` | Get a tool's full input schema on demand |
| `airis-workflow` | Fetch a task-specific procedure by `topic` (on-demand `workflows/*.yaml` recipes) |
| `airis-exec` | Compat router: execute any tool by name/`server:tool`, for clients that can't act on a bare `tools/list` name |

`META_TOOLS_MODE=full` adds `airis-confidence`, `airis-repo-index`, `airis-suggest`,
`airis-route`. Set `COLD_TOOLS_IN_LIST=false` to fall back to the old meta-tool-only
listing for context-constrained clients.

### Request flow

1. `tools/list` returns the meta-tools, any already-active HOT server tools (full
   schema), and every discoverable COLD server's tools (lazy stub schema) — all listed
   directly, no meta-tool round trip needed to see them.
2. The model calls a COLD tool by the name it already saw in `tools/list`
   (`tools/call`) — one hop. The server auto-discovers and auto-enables that COLD
   server on this first call, then runs the tool.
3. `airis-find`/`airis-schema` remain available for browsing servers and fetching full
   schemas when the stub schema isn't enough to know what to pass. `airis-workflow`
   fetches a task-specific procedure by topic. `airis-exec` remains as a compat router
   for clients that can't call a bare `tools/list` name directly.

### Hot / cold / disabled

| State | Behavior | Examples |
|-------|----------|----------|
| **HOT** | Pre-warmed at startup, always listed in `tools/list` with full schema, never idle-killed | `context7`, `airis-mcp-gateway-control`, `airis-workspace` |
| **COLD** | Listed directly in `tools/list` with a lazy stub schema; starts on first tool call, stops after idle timeout, restarts transparently | Stripe, Tavily, browser automation |
| **Disabled** | Gated by policy or absent credentials — never advertised, never run | Supabase (never authorized), dangerous write/admin integrations, niche providers |

```
Claude Code
    |
    v
airis-mcp-gateway (port 9400)
    |
    +-- Dynamic MCP control plane (airis-find, airis-schema, airis-workflow, airis-exec)
    |
    +-- Native helpers (airis-confidence, airis-repo-index, airis-suggest, airis-route)
    |
    +-- MCP proxy --> Docker MCP Gateway --> mindbase, time, etc. (COLD, direct tools/list exposure)
    |
    +-- Process mgmt --> context7, stripe, playwright, etc.
```

### Schema partitioning

`tools/list` strips verbose JSON schemas and injects a synthetic `expandSchema` tool.
Clients call `expandSchema` (or `airis-schema`) on demand for the one tool they need,
saving significant tokens per `initialize`.

---

## The problem it solves

Traditional MCP exposes every tool directly:

```text
tools/list → 60+ tools × full descriptions and schemas
```

This bloats the model context and makes large providers harder to use. The worst
offenders are providers with many unrelated tools — Stripe (customers, checkout,
invoices, subscriptions, refunds, webhooks), Supabase (SQL, auth, storage, edge
functions, management), GitHub, browser automation.

Dynamic MCP exposes a small control plane instead of a giant flat catalog.

---

## Target direction

> **Status:** direction, not yet shipped. The current control plane uses
> `airis-find` / `airis-schema`; the toolset/`airis-activate` model below is the
> target. See [toolset-roadmap.md](./toolset-roadmap.md) for the phased plan.

AIRIS should evolve from a **server-centric Dynamic MCP** into a **toolset-centric
capability gateway**, keeping these boundaries:

- Execution unit: **server process**
- Discovery unit: **tool**
- Exposure unit: **toolset**
- Knowledge unit: **skill / prompt / resource / hook**

### Why the current design is not enough

The current design is directionally correct (avoid exposing every tool, keep rarely
used servers cold, route through a few meta-tools), but it still has a scaling problem:

- broad meta-tool descriptions still leak too much capability metadata into the initial context
- server-level exposure is too coarse for providers with dozens of tools

### Exposure at the toolset layer

Rather than exposing every tool from a large server up front, expose a small number of
coherent capability slices:

- `stripe.customers`, `stripe.payments`, `stripe.billing`
- `github.issues`, `github.prs`, `github.repos`

Tools remain the actual call boundary (`stripe:create_customer`,
`github:create_issue`) — toolsets are only the exposure boundary. This preserves
precision while avoiding the cost of showing every tool at startup.

### Target request flow

1. `tools/list` returns AIRIS control tools plus already-activated native tools
2. The model identifies the needed capability slice
3. AIRIS activates the toolset (`airis-activate`), cold-starting the provider if needed
4. AIRIS emits `notifications/tools/list_changed`
5. The model calls the selected native tool directly

`airis-find` remains a fallback for ambiguous intent or large catalogs — the default UX
should not depend on it.

### Metadata policy

Maintain compact, indexable metadata per tool instead of relying on raw names or full
schemas: `tool_ref`, `toolset`, `summary`, `tags`, `risk` (`read`/`write`/`admin`),
`latency`, `auth_required`, canonical example. Long guidance belongs in MCP prompts,
resources, project skills, hooks, or repo docs — not in tool descriptions.

### Comparison

| Aspect | Flat MCP | Current Dynamic MCP | Target Dynamic MCP |
|--------|----------|---------------------|--------------------|
| Initial tool surface | Huge | Small | Small |
| Primary execution path | Native tools | Native tools (auto-enable) | Native tools (toolset-activated) |
| Discovery style | Implicit | meta-tool (`airis-find`) | activation-first |
| Large-provider handling | Poor | Better | Better and simpler |

---

## Design principles

1. Minimize always-loaded capability metadata.
2. Keep discovery cheaper than execution.
3. Prefer native tool execution over proxy execution layers.
4. Separate exposure concerns from process lifecycle concerns.
5. Use AIRIS as the policy layer, not just a transport proxy.
6. Prefer stable capability slices over giant flat tool catalogs.

### Non-goals

- one OS process per individual tool
- exposing every provider tool directly in `tools/list`
- storing workflow knowledge only inside tool descriptions
- using MCP for host-local deterministic workflows better served by CLI or skills
- making a proxy meta-tool (`airis-exec`) the long-term primary interface

---

## Cross-repository communication

Services communicate via **API / MCP only** — no git submodules.

- **Routing/proxy/intelligence** features → add to `airis-mcp-gateway`.
- **Persistent storage or memory** features → add to `mindbase`, expose via an MCP tool.
