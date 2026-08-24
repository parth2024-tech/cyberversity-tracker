"""
Repository interfaces (Abstract Base Classes).
Define contracts for data access - implementations in infrastructure layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ai_security_monitor.domain.entities import (
    Analysis,
    Category,
    Digest,
    Entry,
    FetchLog,
    Source,
)


@dataclass
class PaginationParams:
    """Pagination parameters."""
    limit: int = 50
    offset: int = 0

    def __post_init__(self):
        self.limit = max(1, min(self.limit, 200))
        self.offset = max(0, self.offset)


@dataclass
class EntryFilters:
    """Filters for entry queries."""
    category: Category | None = None
    source_id: UUID | None = None
    since: datetime | None = None
    until: datetime | None = None
    search: str | None = None
    pre_cve_only: bool = False
    high_velocity_only: bool = False
    analyzed_only: bool = False
    unanalyzed_only: bool = False


class EntryRepository(ABC):
    """Repository for Entry entities."""

    @abstractmethod
    async def add(self, entry: Entry) -> Entry:
        """Add a new entry. Returns entry with generated ID."""
        ...

    @abstractmethod
    async def get(self, entry_id: UUID) -> Entry | None:
        """Get entry by ID."""
        ...

    @abstractmethod
    async def get_by_content_hash(self, content_hash: str) -> Entry | None:
        """Get entry by content hash (for deduplication)."""
        ...

    @abstractmethod
    async def list(
        self,
        filters: EntryFilters | None = None,
        pagination: PaginationParams | None = None,
    ) -> list[Entry]:
        """List entries with optional filters and pagination."""
        ...

    @abstractmethod
    async def count(self, filters: EntryFilters | None = None) -> int:
        """Count entries matching filters."""
        ...

    @abstractmethod
    async def update(self, entry: Entry) -> Entry:
        """Update an existing entry."""
        ...

    @abstractmethod
    async def delete(self, entry_id: UUID) -> bool:
        """Delete entry by ID. Returns True if deleted."""
        ...

    @abstractmethod
    async def get_unanalyzed(
        self,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[Entry]:
        """Get entries that haven't been analyzed yet."""
        ...

    @abstractmethod
    async def get_by_category(
        self,
        category: Category,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[Entry]:
        """Get entries by category."""
        ...


class AnalysisRepository(ABC):
    """Repository for Analysis entities."""

    @abstractmethod
    async def add(self, analysis: Analysis) -> Analysis:
        """Add a new analysis."""
        ...

    @abstractmethod
    async def get(self, entry_id: UUID) -> Analysis | None:
        """Get analysis by entry ID."""
        ...

    @abstractmethod
    async def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        """Get analysis by its own ID."""
        ...

    @abstractmethod
    async def update(self, analysis: Analysis) -> Analysis:
        """Update an existing analysis."""
        ...

    @abstractmethod
    async def delete(self, entry_id: UUID) -> bool:
        """Delete analysis by entry ID."""
        ...

    @abstractmethod
    async def count_high_velocity(self, threshold: int = 70) -> int:
        """Count analyses with threat_velocity >= threshold."""
        ...

    @abstractmethod
    async def count_pre_cve_warnings(self) -> int:
        """Count pre-CVE warning analyses."""
        ...


class SourceRepository(ABC):
    """Repository for Source entities."""

    @abstractmethod
    async def add(self, source: Source) -> Source:
        """Add a new source."""
        ...

    @abstractmethod
    async def get(self, source_id: UUID) -> Source | None:
        """Get source by ID."""
        ...

    @abstractmethod
    async def get_by_name(self, name: str) -> Source | None:
        """Get source by name."""
        ...

    @abstractmethod
    async def list(self, enabled_only: bool = False) -> list[Source]:
        """List all sources."""
        ...

    @abstractmethod
    async def update(self, source: Source) -> Source:
        """Update an existing source."""
        ...

    @abstractmethod
    async def delete(self, source_id: UUID) -> bool:
        """Delete source by ID."""
        ...


class FetchLogRepository(ABC):
    """Repository for FetchLog entities."""

    @abstractmethod
    async def add(self, log: FetchLog) -> FetchLog:
        """Add a fetch log entry."""
        ...

    @abstractmethod
    async def get_recent(self, hours: int = 24, limit: int = 100) -> list[FetchLog]:
        """Get recent fetch logs."""
        ...

    @abstractmethod
    async def get_by_source(self, source_id: UUID, limit: int = 10) -> list[FetchLog]:
        """Get fetch logs for a specific source."""
        ...


class DigestRepository(ABC):
    """Repository for Digest entities."""

    @abstractmethod
    async def add(self, digest: Digest) -> Digest:
        """Add a new digest."""
        ...

    @abstractmethod
    async def get(self, digest_id: UUID) -> Digest | None:
        """Get digest by ID."""
        ...

    @abstractmethod
    async def get_latest(self, schedule: str) -> Digest | None:
        """Get latest digest for a schedule."""
        ...

    @abstractmethod
    async def list(self, limit: int = 10) -> list[Digest]:
        """List recent digests."""
        ...

    @abstractmethod
    async def update(self, digest: Digest) -> Digest:
        """Update a digest."""
        ...
