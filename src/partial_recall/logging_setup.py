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

from partial_recall.logging_sanitize import sanitize_event_dict

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_FORMATS = {"human", "json"}


class _LogStream:
    """Writable stream proxy that survives pytest/Typer capture teardown."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def _candidates(self) -> list[TextIO]:
        streams: list[TextIO] = []
        if self._stream is not None:
            streams.append(self._stream)
        streams.append(sys.stderr)
        if sys.__stderr__ is not sys.stderr:
            streams.append(sys.__stderr__)
        return streams

    def write(self, message: str) -> int:
        for stream in self._candidates():
            if getattr(stream, "closed", False):
                continue
            try:
                return stream.write(message)
            except ValueError:
                continue
        return len(message)

    def flush(self) -> None:
        for stream in self._candidates():
            if getattr(stream, "closed", False):
                continue
            try:
                stream.flush()
                return
            except ValueError:
                continue

    def isatty(self) -> bool:
        for stream in self._candidates():
            if getattr(stream, "closed", False):
                continue
            return stream.isatty() if hasattr(stream, "isatty") else False
        return False


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

    output_stream = _LogStream(stream)

    # Standard library logging — structlog forwards through it.
    logging.basicConfig(
        format="%(message)s",
        stream=output_stream,
        level=getattr(logging, level),
        force=True,
    )

    # Do NOT mute pypdf. Its "Ignoring wrong pointing object" warnings
    # are honest reports that the indexer had to recover from a malformed
    # PDF; a scholar deserves to know something happened to their corpus,
    # not have it silently swallowed. The CLI commands that call into
    # pypdf (currently `index`) are responsible for printing a plain-
    # English explanation once at start so those warnings are legible
    # when they fire.

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Defence-in-depth: redact sensitive keys and home paths in every
        # record. Placed AFTER context-merge so it sees contextvars too.
        sanitize_event_dict,
    ]

    renderer: structlog.types.Processor
    if format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=output_stream.isatty()
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
        logger_factory=structlog.PrintLoggerFactory(file=output_stream),
        cache_logger_on_first_use=False,
    )
