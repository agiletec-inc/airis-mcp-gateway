"""add secrets table

Revision ID: 002
Revises: 001
Create Date: 2025-01-14

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create secrets table
    op.create_table(
        "secrets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_name", sa.String(length=255), nullable=False),
        sa.Column("key_name", sa.String(length=255), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_secrets_id"), "secrets", ["id"], unique=False)
    op.create_index(
        op.f("ix_secrets_server_name"), "secrets", ["server_name"], unique=False
    )
    op.create_index(
        "ix_secrets_server_key", "secrets", ["server_name", "key_name"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_secrets_server_key", table_name="secrets")
    op.drop_index(op.f("ix_secrets_server_name"), table_name="secrets")
    op.drop_index(op.f("ix_secrets_id"), table_name="secrets")
    op.drop_table("secrets")
