"""Pydantic schemas for MCP server state management"""

from pydantic import BaseModel, Field
from datetime import datetime


class MCPServerStateBase(BaseModel):
    """Base server state schema"""

    server_id: str = Field(..., description="MCP server ID")
    enabled: bool = Field(default=False, description="Enable/disable state")


class MCPServerStateCreate(MCPServerStateBase):
    """Schema for creating server state"""

    pass


class MCPServerStateUpdate(BaseModel):
    """Schema for updating server state"""

    enabled: bool = Field(..., description="New enable/disable state")


class MCPServerStateResponse(MCPServerStateBase):
    """Schema for server state response"""

    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MCPServerStateListResponse(BaseModel):
    """Schema for list of server states"""

    server_states: list[MCPServerStateResponse]
    total: int
