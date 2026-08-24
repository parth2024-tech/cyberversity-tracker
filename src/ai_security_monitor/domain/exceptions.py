"""
Domain exceptions - business logic errors.
"""

from typing import Optional


class DomainError(Exception):
    """Base domain exception."""
    def __init__(self, message: str, code: str = "DOMAIN_ERROR", details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class SourceError(DomainError):
    """Source-related errors."""
    pass


class SourceNotFoundError(SourceError):
    def __init__(self, source_id: str):
        super().__init__(f"Source not found: {source_id}", "SOURCE_NOT_FOUND", {"source_id": source_id})


class SourceDisabledError(SourceError):
    def __init__(self, source_id: str):
        super().__init__(f"Source is disabled: {source_id}", "SOURCE_DISABLED", {"source_id": source_id})


class FetchError(DomainError):
    """Feed fetching errors."""
    pass


class FetchTimeoutError(FetchError):
    def __init__(self, source_name: str, timeout: int):
        super().__init__(
            f"Fetch timeout for {source_name} after {timeout}s",
            "FETCH_TIMEOUT",
            {"source_name": source_name, "timeout": timeout}
        )


class FetchRateLimitedError(FetchError):
    def __init__(self, source_name: str, retry_after: int):
        super().__init__(
            f"Rate limited for {source_name}, retry after {retry_after}s",
            "FETCH_RATE_LIMITED",
            {"source_name": source_name, "retry_after": retry_after}
        )


class FetchParseError(FetchError):
    def __init__(self, source_name: str, reason: str):
        super().__init__(
            f"Failed to parse feed from {source_name}: {reason}",
            "FETCH_PARSE_ERROR",
            {"source_name": source_name, "reason": reason}
        )


class AnalysisError(DomainError):
    """Analysis errors."""
    pass


class AnalysisNotFoundError(AnalysisError):
    def __init__(self, entry_id: str):
        super().__init__(f"Analysis not found for entry: {entry_id}", "ANALYSIS_NOT_FOUND", {"entry_id": entry_id})


class AnalyzerUnavailableError(AnalysisError):
    def __init__(self, model: str, reason: str):
        super().__init__(
            f"Analyzer {model} unavailable: {reason}",
            "ANALYZER_UNAVAILABLE",
            {"model": model, "reason": reason}
        )


class DeliveryError(DomainError):
    """Delivery errors."""
    pass


class DeliveryChannelError(DeliveryError):
    def __init__(self, channel: str, reason: str):
        super().__init__(
            f"Delivery failed via {channel}: {reason}",
            "DELIVERY_CHANNEL_ERROR",
            {"channel": channel, "reason": reason}
        )


class DeliveryConfigError(DeliveryError):
    def __init__(self, channel: str, missing: list[str]):
        super().__init__(
            f"Delivery config incomplete for {channel}: missing {missing}",
            "DELIVERY_CONFIG_ERROR",
            {"channel": channel, "missing": missing}
        )


class RepositoryError(DomainError):
    """Repository/data access errors."""
    pass


class EntityNotFoundError(RepositoryError):
    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(
            f"{entity_type} not found: {entity_id}",
            "ENTITY_NOT_FOUND",
            {"entity_type": entity_type, "entity_id": entity_id}
        )


class DuplicateEntryError(RepositoryError):
    def __init__(self, content_hash: str):
        super().__init__(
            f"Entry with content hash already exists: {content_hash}",
            "DUPLICATE_ENTRY",
            {"content_hash": content_hash}
        )