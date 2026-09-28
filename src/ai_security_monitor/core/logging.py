import logging
import sys
from typing import Any

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer, TimeStamper

from ai_security_monitor.config.settings import settings


def setup_logging() -> None:
    """Configure structured logging."""
    log_level = settings.logging.level.upper()

    # Shared processors
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Any
    if settings.logging.format == "json":
        # Production JSON logging
        renderer = JSONRenderer()
    else:
        # Development console logging
        renderer = ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processor=renderer,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    stdlib_root = logging.getLogger()
    stdlib_root.handlers = [handler]
    stdlib_root.setLevel(log_level)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def get_logger(name: str | None = None) -> Any:
    """Get a structured logger."""
    return structlog.get_logger(name)
