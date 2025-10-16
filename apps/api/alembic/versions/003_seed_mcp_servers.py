"""Seed MCP servers from config

Revision ID: 003
Revises: 002
Create Date: 2025-10-16

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from datetime import datetime
import json

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed initial MCP server configurations from mcp-config.json"""

    # Get connection for bulk insert
    conn = op.get_bind()

    # Define server configurations
    servers = [
        # === ENABLED SERVERS (no auth required) ===
        {
            'name': 'filesystem',
            'enabled': True,
            'command': 'docker',
            'args': [
                'run', '--rm', '-i',
                '--network', 'airis-mcp-gateway_default',
                '-v', '/Users/kazuki/github:/workspace:ro',
                'node:24-alpine',
                'sh', '-c', 'npx -y @modelcontextprotocol/server-filesystem /workspace'
            ],
            'env': None,
            'description': 'File system operations for workspace (Docker isolated, read-only)',
            'category': 'Docker Server'
        },
        {
            'name': 'context7',
            'enabled': True,
            'command': 'npx',
            'args': ['-y', '@upstash/context7-mcp'],
            'env': None,
            'description': 'Context-aware code completion',
            'category': 'Gateway NPX'
        },
        {
            'name': 'serena',
            'enabled': True,
            'command': 'docker',
            'args': [
                'run', '--rm', '-i',
                '--network', 'airis-mcp-gateway_default',
                '-v', '/Users/kazuki/github:/workspaces/projects:rw',
                'ghcr.io/oraios/serena:latest',
                'serena', 'start-mcp-server',
                '--context', 'ide-assistant',
                '--enable-web-dashboard', 'false',
                '--enable-gui-log-window', 'false'
            ],
            'env': None,
            'description': 'Serena IDE assistant via Docker',
            'category': 'Docker Server'
        },
        {
            'name': 'puppeteer',
            'enabled': True,
            'command': 'npx',
            'args': ['-y', '@modelcontextprotocol/server-puppeteer'],
            'env': None,
            'description': 'Browser automation and web scraping',
            'category': 'Gateway NPX'
        },
        {
            'name': 'sqlite',
            'enabled': True,
            'command': 'npx',
            'args': ['-y', 'mcp-server-sqlite', '--db-path', '/app/data.db'],
            'env': None,
            'description': 'SQLite database operations',
            'category': 'Gateway NPX'
        },
        {
            'name': 'mindbase',
            'enabled': True,
            'command': 'docker',
            'args': [
                'run', '--rm', '-i',
                '--network', 'airis-mcp-gateway_default',
                '-e', 'MINDBASE_API_URL=http://host.docker.internal:18002',
                '-v', '/Users/kazuki/github/airis-mcp-gateway/servers/mindbase:/app:ro',
                '-w', '/app',
                'node:24-alpine',
                'node', 'dist/index.js'
            ],
            'env': None,
            'description': 'Mindbase knowledge graph operations',
            'category': 'Docker Server'
        },

        # === DISABLED SERVERS (auth required - enable via UI) ===

        # AI SEARCH & RESEARCH
        {
            'name': 'tavily',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@tavily/mcp-server'],
            'env': {'TAVILY_API_KEY': '${TAVILY_API_KEY}'},
            'description': 'AI-powered web search and research',
            'category': 'AI Search & Research'
        },

        # DATABASE & BACKEND
        {
            'name': 'supabase',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@supabase/mcp-server-supabase'],
            'env': {
                'SUPABASE_URL': '${SUPABASE_URL}',
                'SUPABASE_ANON_KEY': '${SUPABASE_ANON_KEY}'
            },
            'description': 'Supabase backend operations',
            'category': 'Database & Backend'
        },
        {
            'name': 'mongodb',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@mongodb/mcp-server'],
            'env': {'MONGODB_CONNECTION_STRING': '${MONGODB_CONNECTION_STRING}'},
            'description': 'MongoDB database operations',
            'category': 'Database & Backend'
        },
        {
            'name': 'mcp-postgres-server',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', 'mcp-postgres-server', '--dsn', '${POSTGRES_CONNECTION_STRING}'],
            'env': None,
            'description': 'PostgreSQL database operations',
            'category': 'Database & Backend'
        },

        # PRODUCTIVITY & COLLABORATION
        {
            'name': 'notion',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@notionhq/mcp-server'],
            'env': {'NOTION_API_KEY': '${NOTION_API_KEY}'},
            'description': 'Notion workspace integration',
            'category': 'Productivity & Collaboration'
        },
        {
            'name': 'slack',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@modelcontextprotocol/server-slack'],
            'env': {
                'SLACK_BOT_TOKEN': '${SLACK_BOT_TOKEN}',
                'SLACK_TEAM_ID': '${SLACK_TEAM_ID}'
            },
            'description': 'Slack messaging and collaboration',
            'category': 'Productivity & Collaboration'
        },
        {
            'name': 'figma',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@hapins/figma-mcp'],
            'env': {'FIGMA_ACCESS_TOKEN': '${FIGMA_ACCESS_TOKEN}'},
            'description': 'Figma design integration',
            'category': 'Productivity & Collaboration'
        },

        # PAYMENT & API INTEGRATIONS
        {
            'name': 'stripe',
            'enabled': False,
            'command': 'bash',
            'args': [
                '-c',
                'STRIPE_SECRET_KEY=$(cat /run/secrets/stripe_key 2>/dev/null || echo ${STRIPE_SECRET_KEY}) npx -y @stripe/mcp --tools=all'
            ],
            'env': None,
            'description': 'Stripe payment processing',
            'category': 'Payment & API'
        },
        {
            'name': 'twilio',
            'enabled': False,
            'command': 'bash',
            'args': [
                '-c',
                'TWILIO_ACCOUNT_SID=$(cat /run/secrets/twilio_sid 2>/dev/null || echo ${TWILIO_ACCOUNT_SID}) TWILIO_API_KEY=$(cat /run/secrets/twilio_key 2>/dev/null || echo ${TWILIO_API_KEY}) TWILIO_API_SECRET=$(cat /run/secrets/twilio_secret 2>/dev/null || echo ${TWILIO_API_SECRET}) npx -y @twilio-alpha/mcp'
            ],
            'env': None,
            'description': 'Twilio messaging and voice',
            'category': 'Payment & API'
        },

        # DEVELOPMENT TOOLS
        {
            'name': 'github',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@modelcontextprotocol/server-github'],
            'env': {'GITHUB_PERSONAL_ACCESS_TOKEN': '${GITHUB_PERSONAL_ACCESS_TOKEN}'},
            'description': 'GitHub repository operations',
            'category': 'Development Tools'
        },
        {
            'name': 'brave-search',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@modelcontextprotocol/server-brave-search'],
            'env': {'BRAVE_API_KEY': '${BRAVE_API_KEY}'},
            'description': 'Brave search engine integration',
            'category': 'Development Tools'
        },
        {
            'name': 'sentry',
            'enabled': False,
            'command': 'npx',
            'args': ['-y', '@modelcontextprotocol/server-sentry'],
            'env': {
                'SENTRY_AUTH_TOKEN': '${SENTRY_AUTH_TOKEN}',
                'SENTRY_ORG': '${SENTRY_ORG}'
            },
            'description': 'Sentry error tracking and monitoring',
            'category': 'Development Tools'
        }
    ]

    # Bulk insert servers
    now = datetime.utcnow()
    for server in servers:
        conn.execute(
            sa.text("""
                INSERT INTO mcp_servers
                (name, enabled, command, args, env, description, category, created_at, updated_at)
                VALUES
                (:name, :enabled, :command, CAST(:args AS JSON), CAST(:env AS JSON), :description, :category, :created_at, :updated_at)
            """),
            {
                'name': server['name'],
                'enabled': server['enabled'],
                'command': server['command'],
                'args': json.dumps(server['args']),
                'env': json.dumps(server['env']) if server['env'] else None,
                'description': server['description'],
                'category': server['category'],
                'created_at': now,
                'updated_at': now
            }
        )


def downgrade() -> None:
    """Remove seeded MCP servers"""
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM mcp_servers"))
