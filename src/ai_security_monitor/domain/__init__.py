"""
Domain layer package - pure business logic.
"""

from ai_security_monitor.domain.entities import (
    Analysis,
    AnalysisModel,
    Category,
    Digest,
    Entity,
    Entry,
    FetchLog,
    FetchStatus,
    Source,
    SourceType,
)
from ai_security_monitor.domain.events import (
    DigestDeliveredEvent,
    DigestGeneratedEvent,
    DomainEvent,
    EntryAnalyzedEvent,
    EntryFetchedEvent,
    EventBus,
    EventType,
    FetchCompletedEvent,
    FetchFailedEvent,
    event_bus,
)
from ai_security_monitor.domain.exceptions import (
    AnalysisError,
    AnalysisNotFoundError,
    AnalyzerUnavailableError,
    DeliveryChannelError,
    DeliveryConfigError,
    DeliveryError,
    DomainError,
    DuplicateEntryError,
    EntityNotFoundError,
    FetchError,
    FetchParseError,
    FetchRateLimitedError,
    FetchTimeoutError,
    RepositoryError,
    SourceDisabledError,
    SourceError,
    SourceNotFoundError,
)
from ai_security_monitor.domain.repositories import (
    AnalysisRepository,
    DigestRepository,
    EntryFilters,
    EntryRepository,
    FetchLogRepository,
    PaginationParams,
    SourceRepository,
)
from ai_security_monitor.domain.value_objects import (
    AttackArchetype,
    ContentHash,
    ThreatScore,
    WeaponizationLevel,
)

__all__ = [
    # Entities
    "Entity", "Source", "Entry", "Analysis", "FetchLog", "Digest",
    "Category", "SourceType", "FetchStatus", "AnalysisModel",
    # Exceptions
    "DomainError", "SourceError", "SourceNotFoundError", "SourceDisabledError",
    "FetchError", "FetchTimeoutError", "FetchRateLimitedError", "FetchParseError",
    "AnalysisError", "AnalysisNotFoundError", "AnalyzerUnavailableError",
    "DeliveryError", "DeliveryChannelError", "DeliveryConfigError",
    "RepositoryError", "EntityNotFoundError", "DuplicateEntryError",
    # Events
    "DomainEvent", "EventType", "EntryFetchedEvent", "EntryAnalyzedEvent",
    "FetchCompletedEvent", "FetchFailedEvent", "DigestGeneratedEvent",
    "DigestDeliveredEvent", "EventBus", "event_bus",
    # Repositories
    "EntryRepository", "AnalysisRepository", "SourceRepository",
    "FetchLogRepository", "DigestRepository", "PaginationParams", "EntryFilters",
    # Value Objects
    "ContentHash", "ThreatScore", "WeaponizationLevel", "AttackArchetype",
]
