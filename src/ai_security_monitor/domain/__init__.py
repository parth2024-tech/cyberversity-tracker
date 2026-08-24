"""
Domain layer package - pure business logic.
"""

from ai_security_monitor.domain.entities import (
    Entity, Source, Entry, Analysis, FetchLog, Digest,
    Category, SourceType, FetchStatus, AnalysisModel
)
from ai_security_monitor.domain.exceptions import (
    DomainError, SourceError, SourceNotFoundError, SourceDisabledError,
    FetchError, FetchTimeoutError, FetchRateLimitedError, FetchParseError,
    AnalysisError, AnalysisNotFoundError, AnalyzerUnavailableError,
    DeliveryError, DeliveryChannelError, DeliveryConfigError,
    RepositoryError, EntityNotFoundError, DuplicateEntryError
)
from ai_security_monitor.domain.events import (
    DomainEvent, EventType, EntryFetchedEvent, EntryAnalyzedEvent,
    FetchCompletedEvent, FetchFailedEvent, DigestGeneratedEvent,
    DigestDeliveredEvent, EventBus, event_bus
)
from ai_security_monitor.domain.repositories import (
    EntryRepository, AnalysisRepository, SourceRepository,
    FetchLogRepository, DigestRepository, PaginationParams, EntryFilters
)
from ai_security_monitor.domain.value_objects import (
    ContentHash, ThreatScore, WeaponizationLevel, AttackArchetype
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