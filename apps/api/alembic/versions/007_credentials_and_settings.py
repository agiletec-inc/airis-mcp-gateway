"""add credential and settings tables for MCP connectors

Revision ID: 007
Revises: 006
Create Date: 2025-10-27
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_credentials",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("enc_key", sa.LargeBinary, nullable=False),
        sa.Column(
            "key_version",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
    )

    op.create_table(
        "mcp_settings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "config_json",
            sa.Text,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_index(
        "ix_mcp_credentials_provider",
        "mcp_credentials",
        ["provider"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO mcp_settings(id, enabled, config_json)
        SELECT 'openai', FALSE, '{}'::text
        WHERE NOT EXISTS (
            SELECT 1 FROM mcp_settings WHERE id = 'openai'
        );
        """
    )

    op.execute(
        """
        CREATE TRIGGER set_updated_at_mcp_credentials
        BEFORE UPDATE ON mcp_credentials
        FOR EACH ROW
        EXECUTE FUNCTION trigger_set_updated_at();
        """
    )

    op.execute(
        """
        CREATE TRIGGER set_updated_at_mcp_settings
        BEFORE UPDATE ON mcp_settings
        FOR EACH ROW
        EXECUTE FUNCTION trigger_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_mcp_settings ON mcp_settings;")
    op.execute(
        "DROP TRIGGER IF EXISTS set_updated_at_mcp_credentials ON mcp_credentials;"
    )

    op.drop_index(
        "ix_mcp_credentials_provider",
        table_name="mcp_credentials",
    )
    op.drop_table("mcp_settings")
    op.drop_table("mcp_credentials")
