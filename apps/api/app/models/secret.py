from sqlalchemy import String, LargeBinary, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from ..core.database import Base


class Secret(Base):
    """Encrypted secrets storage model"""

    __tablename__ = "secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    server_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    key_name: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # Composite unique constraint
    __table_args__ = (
        Index('ix_secrets_server_key', 'server_name', 'key_name', unique=True),
    )

    def __repr__(self) -> str:
        return f"<Secret(server={self.server_name}, key={self.key_name})>"
