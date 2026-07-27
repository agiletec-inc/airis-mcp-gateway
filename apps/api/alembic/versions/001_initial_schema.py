"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-10-14

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create mcp_servers table
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("command", sa.String(length=255), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("env", sa.JSON(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes
    op.create_index("ix_mcp_servers_id", "mcp_servers", ["id"], unique=False)
    op.create_index("ix_mcp_servers_name", "mcp_servers", ["name"], unique=True)


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_mcp_servers_name", table_name="mcp_servers")
    op.drop_index("ix_mcp_servers_id", table_name="mcp_servers")

    # Drop table
    op.drop_table("mcp_servers")
