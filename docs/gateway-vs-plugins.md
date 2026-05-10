# MCP Gateway vs Claude Code Plugins

Claude Code has a built-in plugin system (skills, hooks, MCP servers). Here's when to use the Gateway instead.

## Gateway wins: Infrastructure & API services

| Service | Plugin | Gateway | Winner |
|---------|--------|---------|--------|
| Supabase | MCP plugin | `supabase` (cold) | **Gateway** — Docker-isolated, one config |
| Stripe | MCP plugin | `stripe` (cold) | **Gateway** — same reason |
| GitHub | MCP plugin | `github` (cold) | **Gateway** — or just use `gh` CLI |
| Slack | MCP plugin | Add to config | **Gateway** — when needed |
| Context7 | MCP plugin | `context7` (hot) | **Gateway** — 700 tokens, negligible overhead |
| Playwright | MCP plugin | ~~`playwright`~~ | **Neither** — use `playwright-cli` skill (host Chrome, no Docker needed) |

**Why Gateway wins for services:**
- **Docker-isolated** — no host pollution, consistent across machines
- **HOT/COLD control** — plugins are always-on or always-off; Gateway has fine-grained lifecycle management
- **One config file** — `mcp-config.json` manages everything vs scattered plugin installations
- **Token efficient** — Dynamic MCP exposes 7 meta-tools instead of 60+; plugins load metadata (~100 words each) into every conversation

## Plugins win: Host-dependent & workflow tools

| Tool | Why Plugin |
|------|-----------|
| `playwright-cli` | Needs host Chrome browser — can't run inside Docker |
| `superpowers` | Workflow skills (TDD, debugging, planning) — no MCP equivalent |
| `claude-api` | File generation (docx/xlsx/pptx/pdf) — host filesystem access needed |

## Recommended setup

Keep plugins to **4-6 max** (each adds ~100 words of always-loaded metadata):

```
Plugins (host-dependent):     MCP Gateway (Docker-isolated):
├── claude-api (files)        ├── context7 (HOT)
├── superpowers (workflow)    ├── tavily (cold)
└── playwright-cli (browser)  ├── supabase (cold)
                              ├── stripe (cold)
                              ├── cloudflare (cold)
                              └── ... (20+ more, zero cost when cold)
```

> **Rule of thumb:** If it's an API/service → Gateway. If it needs host access or is a workflow pattern → Plugin.
