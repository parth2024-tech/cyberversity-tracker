# Pydantic schemas for Statistics API.

from datetime import datetime

from pydantic import BaseModel


class CategoryStats(BaseModel):
    """Category statistics."""
    category: str
    count: int


class FetchLogStats(BaseModel):
    """Fetch log statistics."""
    source_name: str
    status: str
    entries_new: int
    entries_total: int
    fetched_at: datetime


class StatsResponse(BaseModel):
    """Full statistics response."""
    total_entries: int
    total_sources: int
    by_category: dict[str, int]
    recent_fetches: list[FetchLogStats]
    analyzed_entries: int
    high_velocity_entries: int
    pre_cve_warnings: int
    telegram_configured: bool = False
    is_fetching: bool = False
