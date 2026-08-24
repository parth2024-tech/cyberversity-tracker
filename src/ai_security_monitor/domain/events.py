"""
Domain events - for event-driven architecture.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from enum import Enum

from ai_security_monitor.domain.entities import Entry, Analysis, Source, FetchStatus


class EventType(str, Enum):
    """Types of domain events."""
    ENTRY_FETCHED = "entry_fetched"
    ENTRY_ANALYZED = "entry_analyzed"
    FETCH_COMPLETED = "fetch_completed"
    FETCH_FAILED = "fetch_failed"
    DIGEST_GENERATED = "digest_generated"
    DIGEST_DELIVERED = "digest_delivered"
    SOURCE_ADDED = "source_added"
    SOURCE_UPDATED = "source_updated"


@dataclass(kw_only=True)
class DomainEvent:
    """Base domain event."""
    id: UUID = field(default_factory=uuid4)
    type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    aggregate_id: UUID  # ID of the aggregate this event belongs to
    payload: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class EntryFetchedEvent(DomainEvent):
    """Event fired when a new entry is fetched."""
    type: EventType = EventType.ENTRY_FETCHED
    entry: Entry


@dataclass(kw_only=True)
class EntryAnalyzedEvent(DomainEvent):
    """Event fired when an entry is analyzed."""
    type: EventType = EventType.ENTRY_ANALYZED
    entry_id: UUID
    analysis: Analysis


@dataclass(kw_only=True)
class FetchCompletedEvent(DomainEvent):
    """Event fired when a fetch operation completes."""
    type: EventType = EventType.FETCH_COMPLETED
    source_id: UUID
    source_name: str
    status: FetchStatus
    entries_new: int
    entries_total: int
    duration_ms: int


@dataclass(kw_only=True)
class FetchFailedEvent(DomainEvent):
    """Event fired when a fetch operation fails."""
    type: EventType = EventType.FETCH_FAILED
    source_id: UUID
    source_name: str
    error_message: str
    duration_ms: int


@dataclass(kw_only=True)
class DigestGeneratedEvent(DomainEvent):
    """Event fired when a digest is generated."""
    type: EventType = EventType.DIGEST_GENERATED
    digest_id: UUID
    total_entries: int
    schedule: str


@dataclass(kw_only=True)
class DigestDeliveredEvent(DomainEvent):
    """Event fired when a digest is delivered."""
    type: EventType = EventType.DIGEST_DELIVERED
    digest_id: UUID
    channel: str
    success: bool
    error: Optional[str] = None


# Event handler type
from typing import Callable, Awaitable, TypeVar

T = TypeVar("T", bound=DomainEvent)
EventHandler = Callable[[T], Awaitable[None]]


class EventBus:
    """Simple in-memory event bus for domain events."""

    def __init__(self):
        self._handlers: dict[EventType, list[EventHandler]] = {}

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        if event_type in self._handlers:
            self._handlers[event_type].remove(handler)

    async def publish(self, event: DomainEvent) -> None:
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                # Log but don't fail - events should be fire-and-forget
                pass


# Global event bus instance
event_bus = EventBus()