<p align="center">
  <img src="./assets/demo.gif" width="720" alt="AIRIS MCP Gateway Demo" />
</p>

<h1 align="center">Universal MCP Hub: AIRIS MCP Gateway</h1>

<p align="center">
  <em>The observability-first gateway for all your MCP tools. <b>Connect once, evaluate everywhere.</b></em>
</p>

<p align="center">
  <a href="https://github.com/agiletec-inc/airis-mcp-gateway/blob/main/LICENSE"><img src="https://img.shields.io/github/license/agiletec-inc/airis-mcp-gateway" alt="License" /></a>
  <a href="https://github.com/agiletec-inc/airis-mcp-gateway/actions"><img src="https://img.shields.io/github/actions/workflow/status/agiletec-inc/airis-mcp-gateway/ci.yml?branch=main" alt="CI" /></a>
  <a href="https://github.com/agiletec-inc/airis-mcp-gateway/stargazers"><img src="https://img.shields.io/github/stars/agiletec-inc/airis-mcp-gateway" alt="Stars" /></a>
</p>

---

## 🛠️ Install

Two steps: **(1)** start the gateway itself, **(2)** connect each AI client to it.

### Step 1 — Start the Gateway

Pick whichever fits you.

**Option A — Quick install** (end users, no source checkout)

```bash
curl -fsSL https://raw.githubusercontent.com/agiletec-inc/airis-mcp-gateway/main/install.sh | bash
```

Uses pre-built images from GHCR. Installs to `~/.local/share/airis-mcp-gateway/`, sets up the `airis-gateway` CLI, and initializes the registry. Remove anytime with `airis-gateway --uninstall`.

**Option B — From source** (developers)

```bash
git clone https://github.com/agiletec-inc/airis-mcp-gateway.git
cd airis-mcp-gateway
cp .env.example .env      # then fill in your API keys
docker compose up -d
docker compose logs -f api
```

> **Tip:** With access to the team [Doppler](https://doppler.com) project you can
> bulk-fill the API keys instead of pasting them one by one. Run this right after
> `cp .env.example .env`:
> ```bash
> doppler secrets download --project airis-mcp-gateway --config dev \
>   --format env --no-file >> .env
> ```
> `.env` is gitignored and loaded directly by `docker compose` — no `doppler run`
> runtime injection needed.

Once it is up, the gateway listens on port `9400` — verify with `curl http://localhost:9400/health`.

### Step 2 — Connect Your AI Client

Register the gateway **once per client** as a user-scoped MCP server. One connection exposes every backend MCP server (Stripe, Supabase, GitHub, …).

| Client | Connection Command / Setup |
| :--- | :--- |
| **Claude Code** | `claude mcp add --transport http --scope user airis-gateway http://localhost:9400/mcp/` |
| **Codex** | `codex mcp add airis-gateway --url http://localhost:9400/mcp` |
| **Gemini CLI** | `gemini mcp add --transport sse airis-gateway http://localhost:9400/sse` |
| **Cursor** | Settings > Features > MCP > **Add New MCP Server**<br>Name: `airis-gateway`, Type: `SSE`, URL: `http://localhost:9400/sse` |
| **Windsurf** | Add SSE URL `http://localhost:9400/sse` to `~/.codeium/config.json` |

Codex and Claude Code use Streamable HTTP at `http://localhost:9400/mcp/`. SSE clients (Gemini CLI, Cursor, Windsurf) use `http://localhost:9400/sse`.

> [!NOTE]
> Registering the gateway as a user-scoped MCP server (the commands above) is the **only** install method — one registration is shared across all your projects. There is no separate plugin to install.

> **Tip:** To skip per-tool permission prompts in Claude Code, add `"mcp__airis-gateway__*"` to the `permissions.allow` list in `~/.claude/settings.json`.

---

## 🧠 Why Universal MCP Hub?

### 1. Observability-First (Moving beyond "Vibes")
Stop guessing if your toolset is actually helping. Airis tracks and visualizes real performance, providing the same observability found in platforms like Codex (OTel ready):
- **Token Efficiency**: Measurable reduction in initial context overhead.
- **Workflow Precision**: Tracking **Steps-to-Success (StS)** for complex tasks.
- **Latency & Reliability**: Real-time monitoring of each MCP server's health, latency, and success rates.

### 2. Intelligent Noise Reduction
Even with large context windows, exposing 100+ tools simultaneously leads to "tool selection hallucinations." Airis keeps the initial capability surface small, activates toolsets on demand, and lets models call native tools directly once the right capability slice is exposed.

### 3. Single Source of Truth
No more repeating API keys and server configs across different projects or AI tools. Gateway server definitions live in one global registry, and the gateway runtime reads a single `mcp-config.json`.

## Configuration Policy

AIRIS uses a single global registry at `~/.airis/mcp/registry.json`.

- Repository-local `mcp.json` files are not supported.
- Existing `mcp.json` files should be imported into the global registry, backed up, and removed.
- `airis-gateway init --apply` also deploys AIRIS best-practice assets to Codex, Claude Code, and Gemini.
- Codex and Gemini can be managed automatically by AIRIS.
- Claude Desktop is detected, but its MCP config is not modified automatically.

Use:

```bash
airis-gateway init ~/github
airis-gateway init ~/github --apply
airis-gateway doctor ~/github
```

## AIRIS Best Practices

AIRIS is not only a central MCP registry. It also distributes operating guidance for when to use MCP, CLI, skills, and hooks.

- Check docs before implementing unfamiliar libraries or APIs.
- Use MCP for shared external capabilities with structured I/O.
- Prefer CLI for deterministic local workflows such as `git`, `gh`, `docker`, `pytest`, and Playwright.
- Prefer Playwright CLI over Playwright MCP for normal browser testing because it is faster and more token-efficient.
- Use skills and hooks for workflow guidance, guardrails, and repeatable team conventions.

## How It Works

Airis aggregates the MCP servers registered in [`mcp-config.json`](./mcp-config.json) (~24 entries, roughly half enabled by default) behind a single endpoint — Streamable HTTP at `/mcp/` for Codex / Claude Code, and SSE at `/sse` for Gemini CLI, Cursor, and Windsurf. Your AI agent connects once and gets access to everything that's enabled.

```
Without Gateway:                          With Gateway:
  claude mcp add stripe ...                 claude mcp add airis ...
  claude mcp add tavily ...                 # Done. Every enabled tool available.
  claude mcp add github ...                 # Shared across Gemini, Cursor, etc.
  ... Manage each server individually ...
```

Servers start on-demand when a tool is called and auto-terminate when idle. No resources wasted.

## Architecture

```
Claude / Gemini / Cursor / Windsurf
    │
    ▼ SSE (Unified Interface)
┌─────────────────────────────────────────────────────────┐
│  AIRIS MCP Gateway (The Intelligent Hub)                │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────┐ │
│  │ Intelligent      │  │ Lifecycle        │  │ Auth & │ │
│  │ Routing (Find)   │  │ Manager (On-Demand)│  │ Secrets│ │
│  └──────────────────┘  └──────────────────┘  └────────┘ │
│            │                    │                 │     │
└────────────┼────────────────────┼─────────────────┼─────┘
             ▼                    ▼                 ▼
      [ uvx / npx ]        [ Docker MCP ]    [ Remote SSE ]
    Stripe, Supabase,     Mindbase, Tavily,   Custom APIs
    GitHub, etc.          etc.
```

> See [docs/architecture.md](./docs/architecture.md) for the full system design.

<details>
<summary><h2>Available Servers</h2></summary>

### HOT — pre-warmed at startup, always listed

| Server | Description |
|--------|-------------|
| **context7** | Library documentation lookup |
| **airis-workspace** | Docker-first workspace lifecycle (`manifest.toml` → `airis gen` → `airis up/test/...`) |
| **airis-mcp-gateway-control** | Manage this gateway (servers, config, health) from inside the agent |

### Enabled COLD — start on first tool call, auto-terminate when idle

| Server | Description |
|--------|-------------|
| **airis-commands** | Slash-command toolkit shipped with the gateway |
| **airis-legal** | Japanese court document automation (証拠説明書 / 準備書面) |
| **fetch** | Fetch a URL and return it as markdown |
| **tavily** | Web search via Tavily API |
| **stripe** | Stripe payments API |
| **twilio** | Twilio voice/SMS API |
| **figma** | Figma design files |
| **magic** | UI component generation |
| **chrome-devtools** | Chrome debugging |
| **github** | GitHub API |
| **memory** | Knowledge graph (entities, relations) |
| **serena** | Semantic code retrieval and editing |
| **morphllm** | Code editing with warpgrep |
| **sequential-thinking** | Step-by-step reasoning |

### Disabled — not registered, no advertised tools

| Server | Description |
|--------|-------------|
| **postgres** | Direct PostgreSQL access |
| **supabase** | Supabase database management — disabled, never authorized for this deployment |
| **mindbase** | Local memory substrate (pgvector + Ollama) — disabled, never authorized for this deployment |
| **filesystem** | File system operations |
| **git** | Git operations |
| **time** | Time utilities |

Source of truth: [`mcp-config.json`](./mcp-config.json). HOT servers are always listed in `tools/list`; COLD servers are discovered via `airis-find` and called through `airis-exec`, which auto-enables the server on first call — no manual setup needed.

</details>

## Documentation

- [Architecture](./docs/architecture.md) — System design, Dynamic MCP (current + target), component responsibilities
- [Toolset roadmap](./docs/toolset-roadmap.md) — Phased plan toward toolset-centric exposure
- [Capability selection guide](./docs/capability-selection.md) — When to use MCP vs skills vs hooks vs subagents vs CLI
- [Configuration reference](./docs/configuration.md) — Environment variables, TTL settings, server config
- [Gateway vs Plugins](./docs/gateway-vs-plugins.md) — When to use Gateway vs Claude Code plugins
- [Deployment guide](./docs/DEPLOYMENT.md) — Production setup, API auth, monitoring, reverse proxy
- [Migration guide](./docs/MIGRATION.md) — Version upgrade path
- [Contributing](./CONTRIBUTING.md) — Development setup, Devbox, go-task, PR guidelines

See [docs/](./docs/) for the full index.

## 💖 Support

[agiletec](https://github.com/agiletec-inc) is a one-person studio building these tools full-time and open source. If they earn a spot in your workflow, a sponsorship keeps them maintained and independent.

[![Sponsor agiletec](https://img.shields.io/badge/Sponsor-agiletec-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/agiletec-inc)

---

## License

MIT
