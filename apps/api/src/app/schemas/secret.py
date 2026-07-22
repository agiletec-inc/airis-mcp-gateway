"""Pydantic schemas for secret management"""

from pydantic import BaseModel, Field
from datetime import datetime


class SecretBase(BaseModel):
    """Base secret schema"""

    server_name: str = Field(..., description="MCP server name")
    key_name: str = Field(..., description="Secret key name (e.g., API_KEY, TOKEN)")


class SecretCreate(SecretBase):
    """Schema for creating a new secret"""

    value: str = Field(..., description="Secret value (will be encrypted)")


class SecretUpdate(BaseModel):
    """Schema for updating a secret"""

    value: str = Field(..., description="New secret value (will be encrypted)")


class SecretResponse(SecretBase):
    """Schema for secret response (without value)"""

    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SecretWithValue(SecretResponse):
    """Schema for secret response with decrypted value"""

    value: str = Field(..., description="Decrypted secret value")


class SecretListResponse(BaseModel):
    """Schema for list of secrets"""

    secrets: list[SecretResponse]
    total: int
