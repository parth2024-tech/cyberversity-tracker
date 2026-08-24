# Pydantic schemas for Digest API.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DigestBase(BaseModel):
    """Base digest schema."""
    schedule: str = Field(..., description="Schedule: daily or weekly")
    period_start: datetime = Field(..., description="Period start")
    period_end: datetime = Field(..., description="Period end")
    total_entries: int = Field(default=0, description="Total entries in digest")
    entries_by_category: dict[str, list] = Field(default_factory=dict, description="Entries grouped by category")
    delivery_channels: list[str] = Field(default_factory=list, description="Delivery channels used")


class DigestCreate(DigestBase):
    """Schema for creating a digest."""
    pass


class DigestRead(DigestBase):
    """Schema for reading a digest."""
    id: UUID
    delivered: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class DigestSendRequest(BaseModel):
    """Request to send a digest."""
    schedule: str = Field(..., pattern="^(daily|weekly)$", description="Digest schedule")
    channels: list[str] = Field(default=["console"], description="Delivery channels")
