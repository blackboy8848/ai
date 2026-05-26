"""
backend/config/logging.py
=========================
Configures structlog for structured JSON logging across the entire app.
Every module gets a bound logger with context (module name, trade_id, etc.)
"""

import logging
import sys
import structlog
from config.settings import get_settings

settings = get_settings()


def configure_logging() -> None:
    """
    Call once at app startup (in main.py).
    After this, every module does:
        log = structlog.get_logger(__name__)
    """
    log_level = logging.DEBUG if settings.debug else logging.INFO

    # Standard library logging (captures uvicorn, sqlalchemy, etc.)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Silence noisy libraries in production
    if settings.is_production:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.is_production:
        # JSON output for log aggregators (Loki, Datadog, etc.)
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )
    else:
        # Pretty colored output for local dev
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )