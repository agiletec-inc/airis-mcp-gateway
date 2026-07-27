from sqlalchemy import String, Boolean, JSON, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from ..core.database import Base


class MCPServer(Base):
    """MCP Server configuration model"""

    __tablename__ = "mcp_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    command: Mapped[str] = mapped_column(String(255), nullable=False)
    args: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    env: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)

    # Metadata
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Timestamps (Best Practice: DB-side defaults for reliability)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<MCPServer(name={self.name}, enabled={self.enabled})>"
