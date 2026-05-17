"""structlog configuration for partial-recall.

Two output formats:
- 'human': rich-formatted with colors, for terminal use
- 'json': one JSON object per line, for log aggregation and post-mortem

Default: human to stderr.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

import structlog

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_FORMATS = {"human", "json"}


def configure_logging(
    level: str = "INFO",
    format: str = "human",
    stream: TextIO | None = None,
) -> None:
    """Configure structlog for this process.

    Idempotent: safe to call more than once (re-configures cleanly).
    """
    level = level.upper()
    if level not in _VALID_LEVELS:
        raise ValueError(
            f"invalid log level {level!r}; expected one of {sorted(_VALID_LEVELS)}"
        )
    if format not in _VALID_FORMATS:
        raise ValueError(
            f"invalid log format {format!r}; expected one of {sorted(_VALID_FORMATS)}"
        )

    if stream is None:
        stream = sys.stderr

    # Standard library logging — structlog forwards through it.
    logging.basicConfig(
        format="%(message)s",
        stream=stream,
        level=getattr(logging, level),
        force=True,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    renderer: structlog.types.Processor
    if format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=stream.isatty() if hasattr(stream, "isatty") else False
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=False,
    )
