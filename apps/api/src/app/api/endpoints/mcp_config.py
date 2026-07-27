"""API endpoints for MCP configuration"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from pathlib import Path
import json
import os

router = APIRouter(tags=["mcp-config"])


class MCPServerInfo(BaseModel):
    """MCP Server information from config"""

    id: str
    name: str
    description: str
    category: str
    apiKeyRequired: bool
    recommended: bool
    builtin: bool
    enabled: bool
    command: str
    args: list[str]
    env: dict[str, str] | None = None


class MCPConfigResponse(BaseModel):
    """Response schema for MCP configuration"""

    servers: list[MCPServerInfo]
    total: int


# Server metadata mapping
SERVER_METADATA = {
    # Built-in servers (via --servers flag)
    "time": {
        "name": "Time",
        "description": "Time and date utilities",
        "category": "builtin",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": True,
    },
    "fetch": {
        "name": "Fetch",
        "description": "HTTP requests and API calls",
        "category": "builtin",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": True,
    },
    "git": {
        "name": "Git",
        "description": "Local Git repository management",
        "category": "builtin",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": True,
    },
    "memory": {
        "name": "Memory",
        "description": "Persistent data across sessions",
        "category": "builtin",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": True,
    },
    # Gateway servers (no auth)
    "filesystem": {
        "name": "File System",
        "description": "Local filesystem access (required)",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": False,
    },
    "context7": {
        "name": "Context7",
        "description": "Official documentation lookup",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": False,
    },
    "sequential-thinking": {
        "name": "Sequential Thinking",
        "description": "Token-efficient reasoning",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": False,
    },
    "serena": {
        "name": "Serena",
        "description": "Session persistence and memory",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": False,
    },
    "mindbase": {
        "name": "Mindbase",
        "description": "Cross-session learning (zero-footprint)",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": False,
    },
    "airis-mcp-gateway-control": {
        "name": "Gateway Control",
        "description": "Dynamic MCP server enable/disable orchestration",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": False,
    },
    "puppeteer": {
        "name": "Puppeteer",
        "description": "Headless browser automation (E2E testing only)",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": False,
        "builtin": False,
    },
    "playwright": {
        "name": "Playwright",
        "description": "JavaScript-heavy content extraction",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": False,
    },
    "sqlite": {
        "name": "SQLite",
        "description": "SQLite database operations (enable only for DB work)",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": False,
        "builtin": False,
    },
    # Auth required servers
    "tavily": {
        "name": "Tavily",
        "description": "Primary web search for deep research",
        "category": "auth-required",
        "apiKeyRequired": True,
        "recommended": True,
        "builtin": False,
    },
    "magic": {
        "name": "Magic",
        "description": "UI component generation",
        "category": "auth-required",
        "apiKeyRequired": True,
        "recommended": True,
        "builtin": False,
    },
    "morphllm-fast-apply": {
        "name": "MorphLLM Fast Apply",
        "description": "Pattern-based refactoring and bulk code updates",
        "category": "auth-required",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "stripe": {
        "name": "Stripe",
        "description": "Stripe payments and subscription management",
        "category": "auth-required",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "figma": {
        "name": "Figma",
        "description": "Figma design files and prototype management",
        "category": "auth-required",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    # Disabled but available
    "supabase": {
        "name": "Supabase",
        "description": "Supabase database and auth (for Supabase projects)",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": True,
        "builtin": False,
    },
    "supabase-selfhost": {
        "name": "Supabase Self-host",
        "description": "Self-hosted Supabase integration (PostgREST + PostgreSQL)",
        "category": "custom",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "slack": {
        "name": "Slack",
        "description": "Slack messages and channel management",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "github": {
        "name": "GitHub",
        "description": "GitHub repositories and issue management (when working in GitHub)",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": True,
        "builtin": False,
    },
    "notion": {
        "name": "Notion",
        "description": "Notion pages and database automation",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "brave-search": {
        "name": "Brave Search",
        "description": "Privacy-focused web search (avoid when Tavily is enabled)",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "chrome-devtools": {
        "name": "Chrome DevTools",
        "description": "Performance analysis",
        "category": "gateway",
        "apiKeyRequired": False,
        "recommended": True,
        "builtin": False,
    },
    "sentry": {
        "name": "Sentry",
        "description": "Error tracking and performance monitoring",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "twilio": {
        "name": "Twilio",
        "description": "SMS and voice APIs",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "mongodb": {
        "name": "MongoDB",
        "description": "MongoDB database access",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
    "mcp-postgres-server": {
        "name": "PostgreSQL",
        "description": "PostgreSQL database access",
        "category": "disabled",
        "apiKeyRequired": True,
        "recommended": False,
        "builtin": False,
    },
}


def load_mcp_servers_from_config() -> list[MCPServerInfo]:
    """Read mcp-config.json and return enriched server info list."""
    project_root = Path(
        os.getenv(
            "CONTAINER_PROJECT_ROOT", os.getenv("PROJECT_ROOT", "/workspace/project")
        )
    )
    default_config_path = project_root / "mcp-config.json"
    config_path = Path(os.getenv("MCP_CONFIG_PATH", str(default_config_path)))

    with open(config_path, "r") as f:
        config = json.load(f)

    mcp_servers = config.get("mcpServers", {})

    servers: list[MCPServerInfo] = []
    for server_id, server_config in mcp_servers.items():
        if server_id.startswith("__"):
            continue

        metadata = SERVER_METADATA.get(
            server_id,
            {
                "name": server_id.replace("-", " ").title(),
                "description": f"{server_id} MCP server",
                "category": "custom",
                "apiKeyRequired": True,
                "recommended": False,
                "builtin": False,
            },
        )

        command = str(server_config.get("command", ""))
        args = server_config.get("args", [])
        env = server_config.get("env")
        enabled = server_config.get("enabled", False)

        if not isinstance(args, list):
            args = []
        else:
            args = [str(arg) for arg in args]
        if env is not None and not isinstance(env, dict):
            env = None

        servers.append(
            MCPServerInfo(
                id=server_id,
                command=command,
                args=args,
                env=env,
                enabled=enabled,
                **metadata,
            )
        )

    builtin_servers = ["time", "fetch", "git", "memory"]
    for builtin_id in builtin_servers:
        if not any(s.id == builtin_id for s in servers):
            metadata = SERVER_METADATA[builtin_id]
            servers.append(
                MCPServerInfo(
                    id=builtin_id,
                    command="",
                    args=[],
                    env=None,
                    enabled=True,
                    **metadata,
                )
            )

    return servers


@router.get("/servers", response_model=MCPConfigResponse)
async def get_mcp_servers():
    """
    Get list of available MCP servers from mcp-config.json
    Returns both enabled and disabled servers with metadata
    """
    try:
        servers = load_mcp_servers_from_config()
    except FileNotFoundError as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="mcp-config.json not found"
        ) from exc
    except json.JSONDecodeError as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid JSON in mcp-config.json",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading MCP configuration: {exc}",
        ) from exc

    return {"servers": servers, "total": len(servers)}
