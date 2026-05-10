---
name: mcp-research
description: Use when investigating libraries, APIs, or unfamiliar patterns before implementation — guides doc lookup and web search workflow
---

# MCP Research Workflow

Use this workflow when you need to investigate a library, API, or unfamiliar pattern before writing code.

## Prerequisites

Gateway instructions already tell you WHICH tools map to which domains. This skill teaches you HOW to use them effectively in sequence.

## Workflow

### Step 1: Identify what you need to know

Before reaching for any tool, clarify:
- What library/API/pattern am I investigating?
- What specific question do I need answered? (not just "learn about X")
- Is there a version constraint?

### Step 2: Check official documentation first

Use the Gateway's doc lookup tools (per the Tool Routing Guide in your instructions):
1. Resolve the library identifier
2. Query for the specific topic you need

If the docs answer your question, **stop here**. Do not search the web redundantly.

### Step 3: Web search (only if docs are insufficient)

Use the Gateway's web search tools only when:
- The library has no indexed documentation
- You need community solutions to a specific error or edge case
- You need to compare alternatives or find recent breaking changes

Search with specific, targeted queries — not broad "how to use X" searches.

### Step 4: Synthesize and cite

Before proceeding to implementation:
- Summarize what you found in 2-3 sentences
- Note the source (official docs vs community post vs Stack Overflow)
- Flag if the information might be outdated (check version numbers)

## Decision Points

| Situation | Action |
|-----------|--------|
| Official docs have the answer | Stop. No web search needed |
| Docs exist but topic not covered | Web search for that specific gap |
| No docs indexed at all | Web search directly |
| Found conflicting information | Prefer official docs over community posts |
| Information seems outdated | Note the version and check for newer sources |

## Anti-patterns

- Searching the web before checking official docs (wastes time, less reliable)
- Broad searches like "how to use React" (too vague, use specific queries)
- Not citing sources (makes it impossible to verify later)
- Continuing to search after finding a clear answer (diminishing returns)
