# Pydantic schemas for Entry API.

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID

from ai_security_monitor.domain.entities import Category


class EntryBase(BaseModel):
    """Base entry schema."""
    title: str = Field(..., description="Entry title")
    url: str = Field(..., description="Entry URL")
    summary: str = Field(default="", description="Entry summary")
    category: Category = Field(..., description="Entry category")
    tags: list[str] = Field(default_factory=list, description="Entry tags")
    published_at: datetime = Field(..., description="Publication timestamp")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class EntryCreate(EntryBase):
    """Schema for creating an entry."""
    source_id: UUID = Field(..., description="Source UUID")
    content_hash: str = Field(..., description="SHA256 content hash")


class EntryRead(EntryBase):
    """Schema for reading an entry."""
    id: UUID
    source_id: UUID
    content_hash: str
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EntryWithAnalysis(EntryRead):
    """Entry with analysis included."""
    analysis: Optional["AnalysisRead"] = None

    class Config:
        from_attributes = True


class EntryListResponse(BaseModel):
    """Paginated entry list response."""
    entries: list[EntryRead]
    total: int
    limit: int
    offset: int

    class Config:
        from_attributes = True
