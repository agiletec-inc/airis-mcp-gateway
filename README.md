# 🌉 AIRIS MCP Gateway

**Centralized management for 25 MCP servers. Solves token explosion and editor configuration hell.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

> **Claude Code, Cursor, Windsurf, Zed**—Unified configuration across all editors. Build once, use everywhere.

---

## 🚀 Quick Install

```bash
git clone https://github.com/kazukinakai/airis-mcp-gateway.git ~/github/airis-mcp-gateway
cd ~/github/airis-mcp-gateway
make install
```

**That's it!**

Automatically installs to ALL editors:
- ✅ Claude Code
- ✅ Claude Desktop
- ✅ Cursor
- ✅ Zed

Restart all editors → 25 MCP servers ready everywhere! 🎉

---

### Alternative: Gateway Only (No Editor Config)

```bash
make up  # Start Gateway without modifying editor configs
```

Use this if you want to manually configure editors or just run Gateway as a Docker container.

---

## 💡 Why AIRIS MCP Gateway?

### 🎯 Problems It Solves

#### ❌ Problem 1: Token Explosion
- **Massive tool definitions** → IDE loads all tool definitions at startup
- **Performance degradation** → IDE becomes slow when token threshold is exceeded
- **Wasted resources** → Tool definitions you never use consume capacity

#### ❌ Problem 2: Editor Configuration Hell
```
Cursor     → mcp.json (proprietary format)
Windsurf   → mcp.json (slightly different)
Zed        → mcp.json (different again)
VS Code    → settings.json (completely different)
```
**Result**: Separate MCP configs per editor = Maintenance nightmare

#### ❌ Problem 3: Redundant Startup Per Project
- Each project starts MCP servers individually → Wasted memory/CPU
- API keys scattered across multiple `.env` files → Security risk

---

### ✅ AIRIS MCP Gateway Solutions

#### 🌟 Benefit 1: Zero-Token Startup
- **IDE recognizes only Gateway URL** → Tool definitions not sent (0 tokens)
- **On-demand loading** → Definitions fetched only on explicit request
- **No resource consumption until use** → Zero waste

#### 🌟 Benefit 2: One-Time Setup, Persistent Use
- **Master configuration file** → Symlink `mcp.json` across all editors and projects
- **Auto-propagation** → Gateway updates apply instantly to all environments
- **Editor abstraction** → Completely hides editor-specific format differences

#### 🌟 Benefit 3: Free Customization
- **MIT License** → Free to modify and use commercially
- **Add your own servers** → Just add to `mcp-config.json`
- **Custom server variants** → Freely adjust behavior

#### 🌟 Benefit 4: Zero Host Pollution
- **All servers run in Docker containers** → Mac host stays completely clean
- **No npx/uvx required** → Everything contained in Gateway, no dependency conflicts
- **Easy cleanup** → `make clean` for complete removal

#### 🌟 Benefit 5: Instant Project Switching
- **Gateway always running** → Servers remain active when switching projects
- **Zero downtime** → No interruption to development flow
- **Unified experience** → Same toolset across all projects

#### 🌟 Benefit 6: Enhanced Security
- **Docker secrets integration** → API keys encrypted and centrally stored in Docker
- **No `.env` files** → Eliminates Git leak risk at the root
- **Runtime injection only** → Avoids plaintext storage

---

## 🏗️ Architecture

```
Claude Code / Cursor / Windsurf / Zed
    ↓
Gateway (http://localhost:9090/sse)
│
├─ 🎨 Settings UI (http://localhost:5173)
│   └─ Toggle MCP servers ON/OFF, configuration management
│
├─ 🚀 FastAPI Backend (http://localhost:8001)
│   ├─ /mcp-servers (MCP server management API)
│   └─ /secrets (Secret management API with encryption)
│
├─ 🗄️ PostgreSQL (internal)
│   ├─ mcp_servers (server configuration)
│   └─ secrets (encrypted API keys)
│
└─ 📦 MCP Server Fleet (25 servers)
    │
    ├─ 🔧 Core Tools
    │   ├─ time, fetch, git, memory
    │   ├─ sequentialthinking, context7
    │   ├─ filesystem, brave-search, github
    │
    ├─ 🧠 AI & Research
    │   └─ tavily
    │
    ├─ 🗄️ Database
    │   ├─ supabase, mcp-postgres-server
    │   ├─ mongodb, sqlite
    │
    ├─ 📊 Productivity
    │   ├─ notion, slack, figma
    │
    ├─ 💳 Payments & APIs
    │   ├─ stripe, twilio
    │
    └─ 🛠️ Development
        ├─ serena, puppeteer, sentry
```

**How it works**:
1. **IDE recognizes only Gateway URL** → Tool definitions not sent (0 tokens)
2. **Dynamic on-demand loading** → Definitions fetched only on explicit request
3. **Single configuration file** → Symlink `mcp.json` across all editors/projects
4. **UI/API integration** → Toggle via frontend, encrypted storage in PostgreSQL

---

## 📦 Available MCP Servers (25 Total)

### 🔧 Core Tools

| Server | Description | Auth |
|--------|-------------|------|
| **time** | Current time & date operations | None |
| **fetch** | Web content retrieval | None |
| **git** | Git repository operations | None |
| **memory** | Persistent knowledge storage | None |
| **sequentialthinking** | Complex problem solving | None |
| **context7** | Library documentation search | None |
| **filesystem** | Secure file operations | None |
| **brave-search** | Web/news/image/video search | `BRAVE_API_KEY` |
| **github** | GitHub repository operations | `GITHUB_PERSONAL_ACCESS_TOKEN` |

### 🧠 AI Search & Research

| Server | Description | Auth |
|--------|-------------|------|
| **tavily** | AI agent search engine | `TAVILY_API_KEY` |

### 🗄️ Databases

| Server | Description | Auth |
|--------|-------------|------|
| **supabase** | Official Supabase integration | `SUPABASE_URL`, `SUPABASE_ANON_KEY` |
| **mcp-postgres-server** | PostgreSQL operations (self-hosted Supabase) | `POSTGRES_CONNECTION_STRING` |
| **mongodb** | MongoDB NoSQL database | `MONGODB_CONNECTION_STRING` |
| **sqlite** | SQLite database operations | None |

### 📊 Productivity & Collaboration

| Server | Description | Auth |
|--------|-------------|------|
| **notion** | Notion workspace integration | `NOTION_API_KEY` |
| **slack** | Slack workspace integration | `SLACK_BOT_TOKEN`, `SLACK_TEAM_ID` |
| **figma** | Figma design file access | `FIGMA_ACCESS_TOKEN` |

### 💳 Payments & API Integration

| Server | Description | Auth |
|--------|-------------|------|
| **stripe** | Payment API | `STRIPE_SECRET_KEY` |
| **twilio** | Phone/SMS API | `TWILIO_ACCOUNT_SID`, `TWILIO_API_KEY`, `TWILIO_API_SECRET` |

### 🛠️ Development Tools

| Server | Description | Auth |
|--------|-------------|------|
| **serena** | Symbol search (Python/Go) | None |
| **puppeteer** | Browser automation and web scraping | None |
| **sentry** | Error monitoring and debugging | `SENTRY_AUTH_TOKEN`, `SENTRY_ORG` |

---

## 🔐 Security (Docker Secrets Recommended)

```bash
# Register secrets (first time only)
docker mcp secret set STRIPE_SECRET_KEY=sk_...
docker mcp secret set TWILIO_ACCOUNT_SID=AC...
docker mcp secret set FIGMA_ACCESS_TOKEN=figd_...

# List secrets
docker mcp secret ls

# Remove secrets
docker mcp secret rm STRIPE_SECRET_KEY
```

**Security Benefits**:
- ✅ Encrypted storage in Docker Desktop
- ✅ Cannot commit to Git (zero leak risk)
- ✅ Runtime injection only
- ✅ OrbStack compatible

See [SECRETS.md](./SECRETS.md) for details.

---

## 🎛️ Enable/Disable Servers

**Important**: All servers run inside Gateway, so edit `mcp-config.json`.

```bash
# Edit Gateway configuration
vim ~/github/airis-mcp-gateway/mcp-config.json
```

**Disable**: Remove or comment out server entry
```json
{
  "mcpServers": {
    "context7": { ... },
    "filesystem": { ... }
    // "puppeteer": { ... }  ← Comment out or remove
  }
}
```

**Enable**: Add to `mcp-config.json`
```json
{
  "mcpServers": {
    "your-server": {
      "command": "npx",
      "args": ["-y", "@your/mcp-server"],
      "env": {
        "API_KEY": "${YOUR_API_KEY}"
      }
    }
  }
}
```

Restart:
```bash
make restart
```

---

## 🛠️ Commands

### Essential Commands
| Command | Description |
|---------|-------------|
| `make install` | Install to ALL editors (Claude Desktop, Cursor, Zed, etc.) |
| `make uninstall` | Restore original configs and stop Gateway |
| `make up` | Start Gateway only (no editor config changes) |
| `make down` | Stop all services |

### Basic Operations
| Command | Description |
|---------|-------------|
| `make help` | Show all available commands |
| `make restart` | Restart services |
| `make logs` | Show all logs |
| `make logs-<service>` | Show specific service logs (e.g., `make logs-api`) |
| `make ps` | Show container status |

### Cleanup
| Command | Description |
|---------|-------------|
| `make clean` | Remove Mac host garbage (node_modules, __pycache__, etc.) |
| `make clean-all` | Complete cleanup (includes volumes, ⚠️ data loss) |

### Information
| Command | Description |
|---------|-------------|
| `make info` | List available MCP servers |
| `make config` | Show Docker Compose configuration |

### UI Operations
| Command | Description |
|---------|-------------|
| `make ui-build` | Build Settings UI image |
| `make ui-up` | Start Settings UI |
| `make ui-down` | Stop Settings UI |
| `make ui-logs` | Show Settings UI logs |
| `make ui-shell` | Enter Settings UI shell |

### API Operations
| Command | Description |
|---------|-------------|
| `make api-build` | Build API image |
| `make api-logs` | Show API logs |
| `make api-shell` | Enter API shell (Bash) |

### Database
| Command | Description |
|---------|-------------|
| `make db-migrate` | Run database migrations |
| `make db-shell` | Enter PostgreSQL shell |

### Testing
| Command | Description |
|---------|-------------|
| `make test` | Run configuration validation tests |

### Profile Management
| Command | Description |
|---------|-------------|
| `make profile-list` | List available profiles |
| `make profile-info` | Show current profile configuration |
| `make profile-recommended` | Switch to Recommended profile |
| `make profile-minimal` | Switch to Minimal profile |

---

## 📦 MCP Server Profiles

AIRIS MCP Gateway provides **3 curated profiles** to optimize your development workflow based on project needs and resource constraints.

### 🎯 Profile Comparison

| Profile | Servers | Memory | Use Case |
|---------|---------|--------|----------|
| **Recommended** | filesystem, context7, serena, mindbase | ~500MB | Long-term projects, LLM failure learning |
| **Minimal** | filesystem, context7 | ~50MB | Short tasks, resource constraints |
| **Custom** | User-defined | Variable | Specialized needs |

---

### 1. 📦 Recommended Profile (Default)

**For**: Long-term projects, production development

**Included Servers**:
- Built-in: `time`, `fetch`, `git`, `memory`, `sequentialthinking`
- Gateway: `filesystem`, `context7`, `serena`, `mindbase`

**Key Features**:
- ✅ **Short + Long-term Memory**: `memory` (Built-in) + `mindbase` (persistent conversation history)
- ✅ **LLM Failure Prevention**: `mindbase` tracks errors and prevents repeated mistakes
- ✅ **Code Understanding**: `serena` provides semantic search across codebases
- ✅ **Latest Documentation**: `context7` accesses 15,000+ library docs

**Resource Usage**: ~500MB (includes PostgreSQL + Ollama embedding)

```bash
make profile-recommended
make restart
```

---

### 2. 📦 Minimal Profile

**For**: Quick tasks, resource-constrained environments, experiments

**Included Servers**:
- Built-in: `time`, `fetch`, `git`, `memory`, `sequentialthinking`
- Gateway: `filesystem`, `context7`

**Key Features**:
- ✅ **Lightweight & Fast**: ~50MB memory usage
- ✅ **Essential Functions**: Short-term memory, file access, latest docs
- ✅ **Token Efficient**: Minimal server count reduces token overhead

**Tradeoffs**:
- ❌ No long-term memory (mindbase disabled)
- ❌ No code understanding (serena disabled)
- ❌ No LLM failure learning

**Resource Usage**: ~50MB

```bash
make profile-minimal
make restart
```

---

### 3. 📦 Custom Profile

**For**: Specialized workflows requiring specific server combinations

**Base**: Start with Recommended or Minimal, then selectively enable:

**Optional Servers**:
- `puppeteer` - E2E testing, browser automation
- `sqlite` - Local database operations
- `tavily` - Web search (requires `TAVILY_API_KEY`)
- `supabase` - Supabase database integration
- `github` - GitHub operations (requires `GITHUB_PERSONAL_ACCESS_TOKEN`)

**Create Custom Profile**:
```bash
# Copy template
cp profiles/recommended.json profiles/custom.json

# Edit configuration
vim profiles/custom.json

# Apply (manual edit mcp-config.json)
vim mcp-config.json
make restart
```

---

### 🧠 Memory Architecture: Why Recommended?

**memory (Built-in)** vs **mindbase (Gateway Docker)**

| Feature | Minimal | Recommended |
|---------|---------|-------------|
| **Short-term memory** | ✅ memory | ✅ memory |
| **Long-term memory** | ❌ None | ✅ mindbase |
| **Failure learning** | ❌ None | ✅ mindbase (`error` category) |
| **Progress tracking** | ❌ None | ✅ mindbase (`decision`, `progress`) |
| **Code understanding** | ❌ None | ✅ serena (semantic search) |

**Recommended Profile Advantages**:
- **LLM Failure Prevention**: mindbase records errors (`category: error`) and prevents Claude from repeating the same mistakes
- **Decision Tracking**: mindbase tracks latest decisions (`category: decision`) for consistent judgment
- **Semantic Search**: mindbase + serena enable conversation history search and code understanding
- **Time-series Management**: mindbase maintains session hierarchy and temporal decay

**When to Choose Minimal**:
- Short-term tasks (< 1 day)
- Resource-constrained environments
- Simple scripts or experiments
- Token efficiency is critical

---

### 📋 Profile Selection Guide

| Situation | Profile | Reason |
|-----------|---------|--------|
| Long-term development project | Recommended | Memory + Learning features |
| Short task or experiment | Minimal | Lightweight, fast |
| Resource-constrained environment | Minimal | ~50MB memory usage |
| LLM keeps repeating mistakes | Recommended | mindbase error tracking |
| Need code understanding | Recommended | serena semantic search |
| Need conversation history | Recommended | mindbase persistent storage |
| E2E testing required | Custom | Add puppeteer |
| Working with Supabase | Custom | Add supabase |

---

### 🔄 Switching Profiles

```bash
# Check current profile
make profile-info

# List available profiles
make profile-list

# Switch to Recommended
make profile-recommended
make restart

# Switch to Minimal
make profile-minimal
make restart
```

**Important**: Always run `make restart` after switching profiles to apply changes.

---

### 📚 Learn More

- **[profiles/README.md](profiles/README.md)** - Detailed profile documentation
- **[docs/mcp-best-practices.md](docs/mcp-best-practices.md)** - Memory architecture & best practices
- **[MindBase Repository](https://github.com/kazukinakai/mindbase)** - Long-term memory system

---

## 🌐 Multi-Editor & Multi-Project Support

### Unified Management

```
~/github/airis-mcp-gateway/mcp.json (master config)
    ↓ symlink
├─ ~/.claude/mcp.json (Claude Code global)
├─ ~/github/agiletec/mcp.json (agiletec project)
├─ ~/github/neural/mcp.json (neural project)
└─ ~/github/storage-smart/mcp.json (storage-smart project)
```

**Benefits**:
- Master config updates → Auto-propagate to all editors and projects
- Abstract editor-specific differences
- Gateway stays resident when switching projects

**Add Project**:
```bash
ln -sf ~/github/airis-mcp-gateway/mcp.json ~/github/your-project/mcp.json
```

---

## 📁 File Structure

```
airis-mcp-gateway/
├── docker-compose.yml      # All service definitions (Gateway + DB + API + UI)
├── mcp-config.json         # Gateway configuration (internal MCP servers)
├── mcp.json                # Client configuration (editor side)
├── .env.example            # Environment variable template
├── Makefile                # Standardized commands (makefile-global compliant)
│
├── apps/
│   ├── api/                # FastAPI Backend
│   │   ├── app/
│   │   │   ├── api/        # API endpoints
│   │   │   ├── core/       # Encryption & configuration
│   │   │   ├── crud/       # Database operations
│   │   │   ├── models/     # SQLAlchemy models
│   │   │   └── schemas/    # Pydantic schemas
│   │   ├── alembic/        # Migrations
│   │   └── Dockerfile
│   │
│   └── settings/           # React + Vite UI
│       ├── src/
│       └── Dockerfile
│
├── tests/                  # Configuration validation tests
│   ├── test_config.py
│   └── conftest.py
│
├── README.md               # This file
└── SECRETS.md              # Secret management guide
```

---

## 🐛 Troubleshooting

### Gateway Startup Failure
```bash
# Check Gateway logs
docker logs airis-mcp-gateway

# Check all service status
make ps

# Clean restart
make clean
make up
```

### API/UI Startup Failure
```bash
# Check API logs
make api-logs

# Check UI logs
make ui-logs

# Check database connection
make db-shell
```

### Configuration File Validation
```bash
# Validate mcp-config.json and mcp.json
make test
```

### Complete Cleanup
```bash
# ⚠️ Warning: Deletes all data (including volumes)
make clean-all
make up
```

### Individual Service Inspection
```bash
# Specific service logs
make logs-mcp-gateway
make logs-api
make logs-postgres

# Detailed container status
docker compose ps
```

---

## 🔗 Editor Integration

Restart editor after:
1. Gateway start/stop
2. `mcp.json` changes
3. Adding new MCP servers

Gateway stays resident, no restart needed when switching projects.

---

## 💖 Support

If this project helps you, please support continued development:

### ☕ Ko-fi
Ongoing development support
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5e5b?logo=kofi&logoColor=white)](https://ko-fi.com/kazukinakai)

### 🎯 Patreon
Monthly support for independence
[![Patreon](https://img.shields.io/badge/Patreon-Support-f96854?logo=patreon&logoColor=white)](https://www.patreon.com/kazukinakai)

### 💜 GitHub Sponsors
Flexible support options
[![GitHub Sponsors](https://img.shields.io/badge/GitHub-Sponsor-ea4aaa?logo=github&logoColor=white)](https://github.com/sponsors/kazukinakai)

**Your support enables**:
- Adding new MCP servers
- Performance optimizations
- Documentation enhancements
- Community support

---

## 🤝 Contributing

Issues and Pull Requests welcome!

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Create Pull Request

---

## 📄 License

MIT License - Free to use

---

## 💬 Author

**Agiletec Inc.** ([@agiletec-inc](https://github.com/agiletec-inc))

Created to solve MCP server token explosion and configuration hell.
