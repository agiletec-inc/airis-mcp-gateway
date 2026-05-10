# Toolset Roadmap

## Objective

Introduce **toolset-centric exposure** without rewriting the entire gateway lifecycle model.

The current process model is usable:

- server process lifecycle already exists
- cold start and idle kill already exist
- tool discovery cache already exists

The missing layer is the capability model between `server` and `tool`.

## Phase 1: Add a toolset catalog

Create a catalog that maps providers to capability slices.

Example:

```json
{
  "stripe": {
    "toolsets": {
      "customers": ["create_customer", "update_customer", "list_customers"],
      "payments": ["create_payment_intent", "capture_payment_intent"],
      "billing": ["create_invoice", "finalize_invoice", "pay_invoice"]
    }
  }
}
```

Requirements:

- checked into the repo
- human-editable
- generated or refreshed from server metadata when possible
- supports aliases, tags, risk level, and examples

Suggested path:

- `config/toolsets/*.json`
- or `catalogs/toolsets/*.yaml`

## Phase 2: Add an AIRIS capability index

Extend the in-memory cache to store:

- server metadata
- tool metadata
- toolset metadata
- tool-to-toolset mapping

Suggested model additions:

- `ToolsetInfo`
- `tool_to_toolset`
- `server_to_toolsets`

This should sit beside the existing `DynamicMCP` structures.

## Phase 3: Change `tools/list`

Current behavior:

- meta-tools
- hot tools
- execution guidance embedded in meta-tools

Target behavior:

- minimal control tools
- optionally already-activated toolsets
- no large embedded global tool listing
- native tools become visible after activation

`airis-exec` should be deprecated as a primary interface, then removed or kept only for compatibility.

## Phase 4: Add activation semantics

Introduce:

- `airis-activate`
- optional resolver support through `airis-find`

Recommended response shape:

```json
{
  "recommended_toolsets": ["stripe.customers"],
  "recommended_tools": ["stripe:create_customer"],
  "activation_required": true
}
```

After activation, AIRIS should emit:

- `notifications/tools/list_changed`

This aligns with MCP tool list change semantics and lets clients refresh visible tools.

## Phase 5: Improve resolver quality

The current search path is mostly lexical.

Add a resolver layer that ranks by:

- exact tool name match
- toolset match
- server match
- tags
- historical success
- read/write risk compatibility
- workspace policy

This can power:

- `airis-find`
- `airis-route`
- `airis-suggest`

But this resolver should not become a mandatory front door for every tool call.

## Phase 6: Split long knowledge out of tool descriptions

Move detailed usage guidance into:

- prompts
- resources
- skills
- docs

Keep tool descriptions short.

Good:

- "Create a Stripe customer."

Bad:

- multi-paragraph tutorials
- long caveat lists
- full JSON examples for every edge case

## Phase 7: Add policy-aware exposure

Support policies like:

- read-only sessions
- no-admin mode
- safe-by-default for production workspaces
- credential-aware filtering

Examples:

- hide `admin` toolsets unless explicitly activated
- expose `read` toolsets first
- disable write toolsets when required env vars are missing

## Phase 8: Add observability

Track:

- resolver hit rate
- activation count per toolset
- cold start latency by server
- abandoned activations
- schema fetch frequency
- wrong-tool retries

These metrics should drive pruning and toolset redesign.

## Recommended code changes

### New structures

- `apps/api/src/app/core/toolset_catalog.py`
- `apps/api/src/app/core/toolset_resolver.py`
- `apps/api/src/app/core/toolset_policy.py`

### Existing files to extend

- `apps/api/src/app/core/dynamic_mcp.py`
- `apps/api/src/app/api/endpoints/mcp_proxy.py`
- `apps/api/src/app/core/process_manager.py`
- `apps/api/src/app/core/tool_suggester.py`
- `routing-table.json`

## Backward-compatible rollout

1. Add toolset catalog without changing existing behavior.
2. Teach `airis-find` to return toolset recommendations.
3. Add `airis-activate`.
4. Expose activated native tools directly.
5. Reduce `airis-exec` description size.
6. Deprecate `airis-exec` as the default path.
7. Remove the broad embedded listing.

## What not to do

- do not create one process per tool
- do not keep giant provider catalogs inside `airis-exec`
- do not require manual server enable/disable for normal usage
- do not depend on full schema fetch for every discovery step
- do not require `airis-find` before every useful tool call

## Success criteria

The redesign is successful when:

- initial `tools/list` stays small and stable
- large providers do not dump huge catalogs into context
- the model can still reach the right native tool in one or two calls
- cold providers feel transparent to the user
- AIRIS becomes the capability and policy layer for agent workflows
