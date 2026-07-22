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

Start the gateway, then call it only from the on-demand client skill.

### Step 1 — Start the Gateway

Pick whichever fits you.

**Option A — Quick install** (end users, no source checkout)

```bash
curl -fsSL https://raw.githubusercontent.com/agiletec-inc/airis-mcp-gateway/main/install.sh | bash
```

Uses pre-built images from GHCR. Installs to `~/.local/share/airis-mcp-gateway/`, sets up the `airis-mcp-gateway` CLI, and initializes the registry. Remove anytime with `airis-mcp-gateway --uninstall`.

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

> [!IMPORTANT]
> The gateway container does not run provider-owned coding agents such as
> `codex mcp-server` or `claude mcp serve`. Those processes must run on the
> host where the user's provider login is available. A future AIRIS local
> provider bridge may connect those host processes to this gateway over a
> local-only transport; provider credentials must never be mounted into the
> gateway container or returned through MCP responses.

### Step 2 — Call It On Demand

Do not register the gateway as a global MCP server. For Codex, use the
`airis-mcp-gateway` skill, which opens a short-lived Streamable HTTP session
to `http://localhost:9400/mcp/` only for the retained Context7 documentation
lookup service.

---

## 🧠 Why Universal MCP Hub?

### 1. Observability-First (Moving beyond "Vibes")
Stop guessing if your toolset is actually helping. Airis tracks and visualizes real performance, providing the same observability found in platforms like Codex (OTel ready):
- **Token Efficiency**: Measurable reduction in initial context overhead.
- **Workflow Precision**: Tracking **Steps-to-Success (StS)** for complex tasks.
- **Latency & Reliability**: Real-time monitoring of each MCP server's health, latency, and success rates.

### 2. Intelligent Noise Reduction
Even with large context windows, exposing 100+ tools simultaneously leads to "tool selection hallucinations." Airis keeps the initial capability surface small, activates toolsets on demand, and lets models call native tools directly once the right capability slice is exposed.

### 3. Small, Explicit Surface
`mcp-config.json` contains only Context7. Local file, Git, browser, web, and
external write operations stay with their native tools or purpose-specific skills.

## Configuration Policy

The tracked registry mirror is `mcp-config.json.example`; the local runtime
copy is `mcp-config.json`. Neither file installs a global MCP registration.

## AIRIS Best Practices

AIRIS is not only a central MCP registry. It also distributes operating guidance for when to use MCP, CLI, skills, and hooks.

- Check docs before implementing unfamiliar libraries or APIs.
- Use MCP for shared external capabilities with structured I/O.
- Prefer CLI for deterministic local workflows such as `git`, `gh`, `docker`, `pytest`, and Playwright.
- Prefer Playwright CLI over Playwright MCP for normal browser testing because it is faster and more token-efficient.
- Use skills and hooks for workflow guidance, guardrails, and repeatable team conventions.

## How It Works

AIRIS exposes Context7 through a local Streamable HTTP endpoint. The client
skill calls it only for exact, current library or framework documentation.

```
Ordinary work: native tools and skills
Exact library docs: AIRIS skill → Context7
```

Context7 starts on demand when the skill calls it.

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

Provider-owned coding agents are intentionally outside this container boundary:

```text
Codex CLI / Claude Code (host, authenticated)
                 │ local-only provider bridge
                 ▼
          AIRIS MCP Gateway (Docker)
```

The bridge is a separate integration boundary, not another credential store in
`mcp-config.json`. Mounting `~/.codex`, `~/.claude`, or equivalent provider
credential directories into the gateway container is unsupported.

> See [docs/architecture.md](./docs/architecture.md) for the full system design.

<details>
<summary><h2>Available Servers</h2></summary>

### HOT — pre-warmed at startup, always listed

| Server | Description |
|--------|-------------|
| **context7** | Library documentation lookup |
| **airis-mcp-gateway-control** | Manage this gateway (servers, config, health) from inside the agent |

### COLD — listed in `tools/list` (lazy stub schema), start on first tool call, auto-terminate when idle

| Server | Description |
|--------|-------------|
| **airis-commands** | Slash-command toolkit shipped with the gateway |
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
| **postgres** | Direct PostgreSQL access |
| **filesystem** | File system operations |
| **git** | Git operations |
| **time** | Time utilities |
| **notebooklm** | NotebookLM notebooks (create, chat, delete) |
| **airis-legal** | agiletec-inc/airis-legal document automation (証拠説明書/準備書面) |

### Policy-disabled — never advertised, never run

| Server | Description |
|--------|-------------|
| **supabase** | Supabase database management — disabled, never authorized for this deployment |
| **mindbase** | Local memory substrate (pgvector + Ollama) — disabled, never authorized for this deployment |
| **cloudflare** | Cloudflare API access (KV, Workers, DNS) — disabled, never authorized for this deployment |

Source of truth: [`mcp-config.json`](./mcp-config.json). HOT servers are always listed in `tools/list` with full schema. COLD servers are also listed directly, with a lazy stub schema (`{"type":"object"}`) — a client can call one by name straight from `tools/list` and it auto-enables on first call, no `airis-find`/`airis-exec` hop needed. `airis-find`/`airis-schema` remain available for browsing servers and fetching full schemas; `airis-workflow` fetches a task-specific procedure by topic; `airis-exec` remains as a compat router for clients that can't act on a bare `tools/list` name.

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
