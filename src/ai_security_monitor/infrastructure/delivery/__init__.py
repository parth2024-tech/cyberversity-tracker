"""
Delivery infrastructure package - plugin registration.
"""

# Import all delivery adapters to register them
from ai_security_monitor.infrastructure.delivery import (
    base,
    console_delivery,
    email_delivery,
    slack_delivery,
    telegram_delivery,
)

from ai_security_monitor.infrastructure.delivery.base import (
    BaseDelivery,
    DeliveryResult,
    delivery_registry,
    DeliveryRegistry,
)

__all__ = [
    "BaseDelivery",
    "DeliveryResult",
    "delivery_registry",
    "DeliveryRegistry",
]