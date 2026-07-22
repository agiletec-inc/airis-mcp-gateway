"""MCP Server state model for enable/disable persistence"""

from sqlalchemy import String, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from ..core.database import Base


class MCPServerState(Base):
    """MCP Server enable/disable state persistence"""

    __tablename__ = "mcp_server_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    server_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps (Best Practice: DB-side defaults for reliability)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<MCPServerState(server={self.server_id}, enabled={self.enabled})>"
