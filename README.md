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

## 🛠️ Quick Install & Universal Setup

### 1. Start the Gateway
```bash
curl -fsSL https://raw.githubusercontent.com/agiletec-inc/airis-mcp-gateway/main/install.sh | bash
```

### Development Setup

```bash
# 1. Copy and fill in your API keys
cp .env.example .env

# 2. Start the gateway
docker compose up -d

# 3. View logs
docker compose logs -f api
```

> **Tip:** For secure secret management, use [Doppler](https://doppler.com) instead of `.env`:
> ```bash
> doppler setup                              # One-time setup
> doppler run -- docker compose up -d        # Injects secrets at runtime
> ```

### 2. Connect Your AI Client
Register the gateway once, and access all backend MCP servers (Stripe, Supabase, GitHub, etc.) through a single connection.

| Client | Connection Command / Setup |
| :--- | :--- |
| **Codex** | `codex mcp add airis-mcp-gateway --url http://localhost:9400/mcp` |
| **Claude Code** | `claude mcp add --transport http --scope user airis-gateway http://localhost:9400/mcp/` |
| **Gemini CLI** | `gemini mcp add --transport sse airis-mcp-gateway http://localhost:9400/sse` |
| **Cursor** | Settings > Features > MCP > **Add New MCP Server**<br>Name: `airis-mcp-gateway`, Type: `SSE`, URL: `http://localhost:9400/sse` |
| **Windsurf** | Add SSE URL `http://localhost:9400/sse` to `~/.codeium/config.json` |

Docker Compose publishes the API on port `9400`. Codex and Claude Code use Streamable HTTP at `http://localhost:9400/mcp/`. SSE clients (Gemini CLI, Cursor, Windsurf) use `http://localhost:9400/sse`.

> [!NOTE]
> The `--scope user` flag registers the server globally across all projects. Do NOT also install via `/install-plugin` — duplicate endpoint causes the plugin's MCP connection to be silently ignored.

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

Airis aggregates 20+ MCP servers behind a single endpoint — Streamable HTTP at `/mcp/` for Codex / Claude Code, and SSE at `/sse` for Gemini CLI, Cursor, and Windsurf. Your AI agent connects once and gets access to everything.

```
Without Gateway:                          With Gateway:
  claude mcp add stripe ...                 claude mcp add airis ...
  claude mcp add supabase ...               # Done. 100+ tools available.
  claude mcp add tavily ...                 # Shared across Gemini, Cursor, etc.
  ... Manage 20 servers individually ...
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

> See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full system design.

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
| **supabase** | Supabase database management |
| **stripe** | Stripe payments API |
| **twilio** | Twilio voice/SMS API |
| **cloudflare** | Cloudflare DNS / Workers / KV |
| **figma** | Figma design files |
| **magic** | UI component generation |
| **chrome-devtools** | Chrome debugging |

### Disabled — auto-enable on first tool call

| Server | Description |
|--------|-------------|
| **github** | GitHub API |
| **postgres** | Direct PostgreSQL access |
| **memory** | Knowledge graph (entities, relations) |
| **mindbase** | Local memory substrate (pgvector + Ollama) |
| **serena** | Semantic code retrieval and editing |
| **morphllm** | Code editing with warpgrep |
| **sequential-thinking** | Step-by-step reasoning |
| **filesystem** | File system operations |
| **git** | Git operations |
| **time** | Time utilities |

Source of truth: [`mcp-config.json`](./mcp-config.json). HOT servers are always listed in `tools/list`; COLD servers are surfaced via `airis-find` and auto-enable on first native tool call — no manual setup needed.

</details>

## Documentation

- [Dynamic MCP deep-dive](./docs/dynamic-mcp.md) — Architecture, cache behavior, auto-enable flow
- [Target architecture](./docs/target-architecture.md) — Toolset-centric AIRIS direction and design boundaries
- [Toolset roadmap](./docs/toolset-roadmap.md) — Phased implementation plan for capability slices
- [Capability selection guide](./docs/capability-selection.md) — When to use MCP vs skills vs hooks vs subagents vs CLI
- [Configuration reference](./docs/configuration.md) — Environment variables, TTL settings, server config
- [Gateway vs Plugins](./docs/gateway-vs-plugins.md) — When to use Gateway vs Claude Code plugins
- [Deployment guide](./DEPLOYMENT.md) — Production setup, API auth, monitoring, reverse proxy
- [Architecture](./ARCHITECTURE.md) — System design and component responsibilities
- [Contributing](./CONTRIBUTING.md) — Development setup, Devbox, go-task, PR guidelines

## License

MIT
