"""add updated_at triggers for automatic timestamp updates

Revision ID: 006
Revises: 005
Create Date: 2025-10-21

Note: PostgreSQL doesn't have built-in ON UPDATE CURRENT_TIMESTAMP like MySQL.
This migration creates triggers to automatically update the updated_at column
whenever a row is updated, regardless of how the update occurs (ORM or raw SQL).

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the trigger function (shared by all tables)
    op.execute("""
        CREATE OR REPLACE FUNCTION trigger_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create triggers for each table
    op.execute("""
        CREATE TRIGGER set_updated_at_secrets
        BEFORE UPDATE ON secrets
        FOR EACH ROW
        EXECUTE FUNCTION trigger_set_updated_at();
    """)

    op.execute("""
        CREATE TRIGGER set_updated_at_mcp_server_states
        BEFORE UPDATE ON mcp_server_states
        FOR EACH ROW
        EXECUTE FUNCTION trigger_set_updated_at();
    """)

    op.execute("""
        CREATE TRIGGER set_updated_at_mcp_servers
        BEFORE UPDATE ON mcp_servers
        FOR EACH ROW
        EXECUTE FUNCTION trigger_set_updated_at();
    """)


def downgrade() -> None:
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_secrets ON secrets;")
    op.execute(
        "DROP TRIGGER IF EXISTS set_updated_at_mcp_server_states ON mcp_server_states;"
    )
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_mcp_servers ON mcp_servers;")

    # Drop the trigger function
    op.execute("DROP FUNCTION IF EXISTS trigger_set_updated_at();")
