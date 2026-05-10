# Dynamic MCP Architecture

## Overview

AIRIS should use Dynamic MCP to keep the initial tool surface small while still allowing direct use of native MCP tools.

The key idea is:

- do not expose every tool up front
- do not force execution through a proxy meta-tool
- activate only the capability slice that is needed
- let the model call native tools directly after activation

## The Problem: Tool Bloat

Traditional MCP exposes every tool directly:

```text
tools/list → 60+ tools × full descriptions and schemas
```

This bloats the model context and makes large providers harder to use.

The worst offenders are providers with many unrelated tools:

- Stripe
- Supabase
- GitHub
- browser automation

## The Lighter Solution

Dynamic MCP should expose a small control plane instead of a giant flat tool catalog.

Recommended control tools:

| Tool | Purpose |
|------|---------|
| `airis-activate` | Activate a toolset or provider slice |
| `airis-schema` | Get schema for a native tool when needed |
| `airis-find` | Optional fallback search across tool and server metadata |

Optional internal helpers may still exist, but they should not be the primary user-facing execution path.

## What should not be primary anymore

`airis-exec` should not be the main entrypoint.

Why:

- it recreates an execution layer on top of MCP
- it adds another tool call before the real tool call
- it pushes large tool listings into a meta-tool description
- it hides native tool semantics behind a string indirection

The preferred path is:

1. activate capability
2. refresh visible tools
3. call native tool directly

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                    LLM Context                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Small Control Plane                             │    │
│  │  ├─ airis-activate                              │    │
│  │  ├─ airis-schema                                │    │
│  │  └─ airis-find (optional fallback)              │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Dynamic MCP Layer                       │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Capability Index                               │    │
│  │  ├─ servers                                     │    │
│  │  ├─ toolsets                                    │    │
│  │  └─ tools                                       │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  ProcessManager                          │
│  ├─ HOT: control-plane helpers                          │
│  ├─ COLD: providers start on demand                     │
│  └─ Disabled: gated by policy or credentials            │
└─────────────────────────────────────────────────────────┘
```

## Recommended request flow

### Normal path

1. `tools/list` returns control tools plus any already-activated native tools
2. The model decides which capability slice it needs
3. AIRIS activates the matching toolset
4. AIRIS emits `notifications/tools/list_changed`
5. The model calls the native MCP tool directly

Example:

```text
User: create a Stripe customer

LLM: airis-activate toolset="stripe.customers"
AIRIS: tools/list_changed
LLM: stripe:create_customer { ... }
```

### When schema is needed

```text
LLM: airis-schema tool="stripe:create_customer"
```

Use this only when arguments are unclear or the tool is structurally complex.

### When search is needed

`airis-find` should be treated as an optional fallback:

- large provider catalogs
- ambiguous intent
- tool name not known
- debugging capability exposure

It should not be required for normal usage if the toolset structure is good.

## Toolset activation

Activation should happen at the toolset level, not the single-tool process level.

Examples:

- `stripe.customers`
- `stripe.billing`
- `supabase.sql`
- `supabase.auth`

After activation:

- the provider may be cold-started if needed
- only that capability slice should become visible
- native tools should become callable directly

## Hot / cold model

### Hot by default

- AIRIS control plane
- lightweight shared helpers

### Cold by default

- Stripe
- Supabase
- GitHub
- browser automation
- other large external providers

### Disabled by default

- admin or dangerous capabilities
- providers without credentials
- niche integrations irrelevant to the current workspace

## Metadata strategy

Do not expose full schemas everywhere.

Maintain compact metadata per tool:

- tool ref
- toolset
- one-line summary
- tags
- risk
- auth requirement

That metadata is enough to guide selection without paying the cost of large descriptions and schemas in every session.

## Comparison

| Aspect | Flat MCP | Old Dynamic MCP | Target Dynamic MCP |
|--------|----------|-----------------|--------------------|
| Initial tool surface | Huge | Small | Small |
| Primary execution path | Native tools | `airis-exec` | Native tools |
| Discovery style | Implicit | meta-tool heavy | activation-first |
| Context cost | High | Medium | Lower |
| Large-provider handling | Poor | Better | Better and simpler |

## Best Practices

1. Prefer direct native tool calls after activation.
2. Keep `airis-find` as fallback, not default.
3. Use `airis-schema` only when argument shape is unclear.
4. Keep provider servers cold unless there is a strong reason to keep them hot.
5. Use toolsets to expose coherent capability slices instead of entire providers.
