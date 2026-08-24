# Pydantic schemas for Source API.

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID

from ai_security_monitor.domain.entities import Category, SourceType, FetchStatus


class SourceBase(BaseModel):
    """Base source schema."""
    name: str = Field(..., description="Source name")
    category: Category = Field(..., description="Source category")
    type: SourceType = Field(..., description="Source type")
    url: str = Field(default="", description="Source URL")
    query: Optional[str] = Field(default=None, description="Query parameter")
    rate_limit_seconds: int = Field(default=3600, description="Rate limit in seconds")
    enabled: bool = Field(default=True, description="Whether source is enabled")
    config: dict = Field(default_factory=dict, description="Type-specific config")


class SourceCreate(SourceBase):
    """Schema for creating a source."""
    pass


class SourceUpdate(BaseModel):
    """Schema for updating a source."""
    name: Optional[str] = None
    category: Optional[Category] = None
    type: Optional[SourceType] = None
    url: Optional[str] = None
    query: Optional[str] = None
    rate_limit_seconds: Optional[int] = None
    enabled: Optional[bool] = None
    config: Optional[dict] = None


class SourceRead(SourceBase):
    """Schema for reading a source."""
    id: UUID
    last_fetched_at: Optional[datetime] = None
    last_status: Optional[FetchStatus] = None
    last_entries_new: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FetchLogRead(BaseModel):
    """Schema for fetch log."""
    id: UUID
    source_id: UUID
    source_name: str
    status: FetchStatus
    entries_new: int
    entries_total: int
    error_message: Optional[str] = None
    duration_ms: int
    fetched_at: datetime

    class Config:
        from_attributes = True
