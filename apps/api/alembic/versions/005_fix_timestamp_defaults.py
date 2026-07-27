"""fix timestamp defaults for secrets and mcp_server_states

Revision ID: 005
Revises: 004
Create Date: 2025-10-21

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fix secrets table timestamps
    op.alter_column(
        "secrets",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "secrets",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    # Fix mcp_server_states table timestamps
    op.alter_column(
        "mcp_server_states",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "mcp_server_states",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def downgrade() -> None:
    # Remove server defaults
    op.alter_column(
        "mcp_server_states",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "mcp_server_states",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=None,
    )

    op.alter_column(
        "secrets",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "secrets",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=None,
    )
