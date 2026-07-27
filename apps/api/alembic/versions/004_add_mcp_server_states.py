"""add mcp_server_states table

Revision ID: 004
Revises: 003
Create Date: 2025-01-18

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create mcp_server_states table
    op.create_table(
        "mcp_server_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_server_states_id"), "mcp_server_states", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_mcp_server_states_server_id"),
        "mcp_server_states",
        ["server_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mcp_server_states_server_id"), table_name="mcp_server_states"
    )
    op.drop_index(op.f("ix_mcp_server_states_id"), table_name="mcp_server_states")
    op.drop_table("mcp_server_states")
