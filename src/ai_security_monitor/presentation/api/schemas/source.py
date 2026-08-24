# Pydantic schemas for Source API.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ai_security_monitor.domain.entities import Category, FetchStatus, SourceType


class SourceBase(BaseModel):
    """Base source schema."""
    name: str = Field(..., description="Source name")
    category: Category = Field(..., description="Source category")
    type: SourceType = Field(..., description="Source type")
    url: str = Field(default="", description="Source URL")
    query: str | None = Field(default=None, description="Query parameter")
    rate_limit_seconds: int = Field(default=3600, description="Rate limit in seconds")
    enabled: bool = Field(default=True, description="Whether source is enabled")
    config: dict = Field(default_factory=dict, description="Type-specific config")


class SourceCreate(SourceBase):
    """Schema for creating a source."""
    pass


class SourceUpdate(BaseModel):
    """Schema for updating a source."""
    name: str | None = None
    category: Category | None = None
    type: SourceType | None = None
    url: str | None = None
    query: str | None = None
    rate_limit_seconds: int | None = None
    enabled: bool | None = None
    config: dict | None = None


class SourceRead(SourceBase):
    """Schema for reading a source."""
    id: UUID
    last_fetched_at: datetime | None = None
    last_status: FetchStatus | None = None
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
    error_message: str | None = None
    duration_ms: int
    fetched_at: datetime

    class Config:
        from_attributes = True
