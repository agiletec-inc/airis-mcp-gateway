from pydantic import BaseModel, Field
from datetime import datetime


class MCPServerBase(BaseModel):
    """Base schema for MCP Server"""

    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = True
    command: str = Field(..., min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    description: str | None = Field(None, max_length=500)
    category: str | None = Field(None, max_length=100)


class MCPServerCreate(MCPServerBase):
    """Schema for creating MCP Server"""

    pass


class MCPServerUpdate(BaseModel):
    """Schema for updating MCP Server"""

    enabled: bool | None = None
    command: str | None = Field(None, min_length=1)
    args: list[str] | None = None
    env: dict[str, str] | None = None
    description: str | None = Field(None, max_length=500)
    category: str | None = Field(None, max_length=100)


class MCPServerResponse(MCPServerBase):
    """Schema for MCP Server response"""

    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MCPServerToggle(BaseModel):
    """Schema for toggling MCP Server"""

    enabled: bool
