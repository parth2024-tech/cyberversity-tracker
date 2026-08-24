"""
Abstract base fetcher and fetcher registry.
Plugin architecture for extensible feed fetching.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID
import asyncio

from ai_security_monitor.domain.entities import Entry, Source, Category, FetchStatus
from ai_security_monitor.domain.exceptions import (
    FetchError, FetchTimeoutError, FetchRateLimitedError, FetchParseError
)
from ai_security_monitor.domain.events import EntryFetchedEvent, FetchCompletedEvent, FetchFailedEvent, event_bus
from ai_security_monitor.config.settings import settings


@dataclass
class FetchResult:
    """Result of a fetch operation."""
    entries: list[Entry]
    entries_new: int
    entries_total: int
    status: FetchStatus
    error_message: Optional[str] = None
    duration_ms: int = 0


class BaseFetcher(ABC):
    """Abstract base class for all fetchers."""

    def __init__(
        self,
        source: Source,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        self.source = source
        self.timeout = timeout or settings.fetch.timeout
        self.max_retries = max_retries or settings.fetch.max_retries
        self._rate_limit_seconds = source.rate_limit_seconds or settings.fetch.rate_limit_default
        self._last_fetch_time: Optional[datetime] = None

    @property
    @abstractmethod
    def fetcher_type(self) -> str:
        """Unique identifier for this fetcher type."""
        ...

    @abstractmethod
    async def _fetch_raw(self) -> list[dict]:
        """Fetch raw data from source. Returns list of raw entry dicts."""
        ...

    @abstractmethod
    def _parse_entry(self, raw: dict) -> Entry:
        """Parse raw entry dict into Entry entity."""
        ...

    async def fetch(self) -> FetchResult:
        """Main fetch method with rate limiting, retries, and error handling."""
        start_time = datetime.utcnow()

        # Rate limiting
        await self._respect_rate_limit()

        # Retry logic
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                raw_entries = await asyncio.wait_for(
                    self._fetch_raw(),
                    timeout=self.timeout,
                )

                # Parse entries
                entries = []
                for raw in raw_entries:
                    try:
                        entry = self._parse_entry(raw)
                        entry.source_id = self.source.id
                        entry.category = self.source.category
                        entries.append(entry)
                    except Exception as e:
                        # Log parse error but continue
                        print(f"Failed to parse entry from {self.source.name}: {e}")
                        continue

                # Publish events for new entries
                for entry in entries:
                    await event_bus.publish(EntryFetchedEvent(
                        aggregate_id=entry.id,
                        entry=entry,
                    ))

                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

                return FetchResult(
                    entries=entries,
                    entries_new=len(entries),  # Will be adjusted by deduplication in service
                    entries_total=len(raw_entries),
                    status=FetchStatus.SUCCESS,
                    duration_ms=duration_ms,
                )

            except asyncio.TimeoutError:
                last_error = FetchTimeoutError(self.source.name, self.timeout)
            except FetchRateLimitedError:
                raise  # Don't retry rate limiting
            except Exception as e:
                last_error = FetchError(str(e))

            # Wait before retry
            if attempt < self.max_retries:
                delay = settings.fetch.retry_delay * (2 ** attempt)  # Exponential backoff
                await asyncio.sleep(delay)

        # All retries exhausted
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        error_msg = str(last_error) if last_error else "Unknown error"

        await event_bus.publish(FetchFailedEvent(
            aggregate_id=self.source.id,
            source_id=self.source.id,
            source_name=self.source.name,
            error_message=error_msg,
            duration_ms=duration_ms,
        ))

        return FetchResult(
            entries=[],
            entries_new=0,
            entries_total=0,
            status=FetchStatus.ERROR,
            error_message=error_msg,
            duration_ms=duration_ms,
        )

    async def _respect_rate_limit(self) -> None:
        """Enforce rate limiting between fetches."""
        if self._last_fetch_time:
            elapsed = (datetime.utcnow() - self._last_fetch_time).total_seconds()
            if elapsed < self._rate_limit_seconds:
                wait_time = self._rate_limit_seconds - elapsed
                await asyncio.sleep(wait_time)

        self._last_fetch_time = datetime.utcnow()


class FetcherRegistry:
    """Registry for fetcher plugins."""

    def __init__(self):
        self._fetchers: dict[str, type[BaseFetcher]] = {}

    def register(self, fetcher_type: str, fetcher_class: type[BaseFetcher]) -> None:
        """Register a fetcher class for a type."""
        self._fetchers[fetcher_type] = fetcher_class

    def get(self, fetcher_type: str) -> type[BaseFetcher]:
        """Get fetcher class by type."""
        if fetcher_type not in self._fetchers:
            raise ValueError(f"No fetcher registered for type: {fetcher_type}")
        return self._fetchers[fetcher_type]

    def create(self, fetcher_type: str, source: Source) -> BaseFetcher:
        """Create fetcher instance for source."""
        fetcher_class = self.get(fetcher_type)
        return fetcher_class(source)

    def list_types(self) -> list[str]:
        """List all registered fetcher types."""
        return list(self._fetchers.keys())


# Global fetcher registry
fetcher_registry = FetcherRegistry()