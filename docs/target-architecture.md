# AIRIS Target Architecture

## Decision

AIRIS should evolve from a **server-centric Dynamic MCP** into a **toolset-centric capability gateway**.

Keep these boundaries:

- Execution unit: **server process**
- Discovery unit: **tool**
- Exposure unit: **toolset**
- Knowledge unit: **skill / prompt / resource / hook**

Repository boundary:

- `airis-mcp-gateway`: shared MCP capability plane
- `airis-monorepo`: repo-local commands, hooks, guards, skills, and workflow automation

This keeps the runtime simple while reducing context bloat for large servers such as Stripe and Supabase.

## Why the current design is not enough

The current Dynamic MCP design is directionally correct:

- avoid exposing every tool directly
- keep rarely used servers cold
- route through a small set of meta-tools

But it still has a scaling problem:

- `airis-exec` adds an extra execution layer that should not be necessary
- broad meta-tool descriptions still leak too much capability metadata into the initial context
- server-level exposure is too coarse for providers with dozens of tools

This becomes expensive when a single server contains multiple unrelated workflows:

- `stripe`: customers, checkout, invoices, subscriptions, refunds, webhooks
- `supabase`: SQL, auth, storage, edge functions, management

## Target model

### 1. Control plane stays hot

Only the AIRIS control plane should be hot by default:

- discovery
- routing
- capability activation
- policy and audit

Examples:

- `airis-activate`
- `airis-schema`
- `airis-find` as optional fallback
- `airis-route` only if it proves materially useful

### 2. Service servers stay cold

Most provider integrations should remain cold:

- Stripe
- Supabase
- Tavily
- Cloudflare
- browser automation

Cold means:

- not started until needed
- stopped after idle timeout
- restarted transparently on demand

### 3. Exposure happens at the toolset layer

Do not expose every tool from a large server up front.

Expose a small number of capability slices instead:

- `stripe.customers`
- `stripe.payments`
- `stripe.billing`
- `supabase.sql`
- `supabase.auth`
- `supabase.storage`

Each toolset contains a small, coherent set of tools.

### 4. Tools remain individually callable

Toolsets are only the exposure boundary.

The actual call boundary remains the tool:

- `stripe:create_customer`
- `stripe:create_payment_intent`
- `supabase:execute_sql`

This preserves precision while avoiding the cost of showing every tool at startup.

## Recommended request flow

### Fast path

1. `tools/list` returns AIRIS control tools plus any already-activated native tools
2. The model identifies the needed capability slice
3. AIRIS activates the toolset if needed
4. AIRIS emits `notifications/tools/list_changed`
5. The model calls the selected native tool directly

### Example

User asks: "Create a Stripe customer and invoice them"

AIRIS should resolve:

- toolset: `stripe.customers`, `stripe.billing`
- primary tools:
  - `stripe:create_customer`
  - `stripe:create_invoice`

The model should not need the full Stripe catalog in advance.

`airis-find` may still help as fallback, but the default UX should not depend on it.

## Metadata policy

Do not rely on raw tool names alone.

Tool names are strong signals, but not enough for accurate routing in larger catalogs. AIRIS should maintain compact metadata per tool:

- `tool_ref`
- `toolset`
- `summary`
- `tags`
- `risk`: `read`, `write`, `admin`
- `latency`
- `auth_required`
- `examples` count or short canonical example

This metadata should be indexable without exposing full JSON Schema by default.

## Hot / cold policy

### Hot by default

- AIRIS internal control tools
- very cheap, high-frequency helpers
- shared MCP control helpers used across clients

### Cold by default

- high-cardinality SaaS providers
- browser automation
- anything with expensive startup or API-key dependence
- low-frequency admin tools

### Disabled by default

- dangerous write/admin integrations
- integrations requiring absent credentials
- niche providers not relevant to the workspace

## Where long guidance should live

Do not pack long explanations into tool descriptions.

Place detailed guidance in:

- MCP prompts
- MCP resources
- project skills
- hooks
- repo docs

Tool descriptions should stay short and operational.

When the guidance is monorepo- or repository-operation-specific, the default home should be `airis-monorepo`, not this gateway repository.

## Design principles

1. Minimize always-loaded capability metadata.
2. Keep discovery cheaper than execution.
3. Prefer native tool execution over proxy execution layers.
4. Separate exposure concerns from process lifecycle concerns.
5. Use AIRIS as the policy layer, not just a transport proxy.
6. Prefer stable capability slices over giant flat tool catalogs.

## Non-goals

- one OS process per individual tool
- exposing every provider tool directly in `tools/list`
- storing workflow knowledge only inside tool descriptions
- using MCP for host-local deterministic workflows that are better served by CLI or skills
- absorbing monorepo command, hook, guard, or skill ownership from `airis-monorepo`
- making `airis-exec` the long-term primary interface

## Target end state

AIRIS should become a capability gateway with:

- small initial tool surface
- on-demand toolset activation
- cold-started providers
- explicit policy and routing
- reusable operational knowledge stored outside raw tool descriptions
