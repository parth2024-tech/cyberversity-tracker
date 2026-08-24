# Structured logging configuration.

import sys
import structlog
from structlog.stdlib import ProcessorFormatter
from structlog.processors import JSONRenderer, TimeStamper, add_log_level
from structlog.dev import ConsoleRenderer

from ai_security_monitor.config.settings import settings


def setup_logging() -> None:
    """Configure structured logging."""
    log_level = settings.logging.level.upper()

    # Shared processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.logging.format == "json":
        # Production JSON logging
        renderer = JSONRenderer()
    else:
        # Development console logging
        renderer = ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging
    handler = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processor=renderer,
    )

    root_logger = structlog.stdlib.get_logger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Also configure stdlib root logger
    import logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def get_logger(name: str = None):
    """Get a structured logger."""
    return structlog.get_logger(name)
