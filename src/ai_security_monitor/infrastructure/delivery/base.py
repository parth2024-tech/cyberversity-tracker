# Abstract base delivery adapter and registry.

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from ai_security_monitor.domain.entities import Analysis, Digest, Entry
from ai_security_monitor.domain.events import DigestDeliveredEvent, event_bus


@dataclass
class DeliveryResult:
    """Result of a delivery operation."""
    success: bool
    channel: str
    message: str = ""
    error: str | None = None


class BaseDelivery(ABC):
    """Abstract base class for all delivery adapters."""

    def __init__(self, config: dict):
        self.config = config
        self.validate_config()

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Unique identifier for this delivery channel."""
        ...

    @abstractmethod
    def validate_config(self) -> None:
        """Validate required configuration."""
        ...

    @abstractmethod
    async def send_digest(self, digest: Digest, entries_with_analysis: list[tuple[Entry, Analysis | None]]) -> DeliveryResult:
        """Send a digest with analyzed entries."""
        ...

    @abstractmethod
    async def send_alert(self, entry: Entry, analysis: Analysis) -> DeliveryResult:
        """Send an immediate alert for a high-priority entry."""
        ...

    async def _publish_delivery_event(self, digest_id: UUID, success: bool, error: str | None = None) -> None:
        """Publish delivery event."""
        await event_bus.publish(DigestDeliveredEvent(
            aggregate_id=digest_id,
            digest_id=digest_id,
            channel=self.channel_name,
            success=success,
            error=error,
        ))


class DeliveryRegistry:
    """Registry for delivery adapters."""

    def __init__(self):
        self._adapters: dict[str, type[BaseDelivery]] = {}

    def register(self, channel: str, adapter_class: type[BaseDelivery]) -> None:
        self._adapters[channel] = adapter_class

    def get(self, channel: str) -> type[BaseDelivery]:
        if channel not in self._adapters:
            raise ValueError(f"No delivery adapter registered for channel: {channel}")
        return self._adapters[channel]

    def create(self, channel: str, config: dict) -> BaseDelivery:
        adapter_class = self.get(channel)
        return adapter_class(config)

    def list_channels(self) -> list[str]:
        return list(self._adapters.keys())


# Global delivery registry
delivery_registry = DeliveryRegistry()
