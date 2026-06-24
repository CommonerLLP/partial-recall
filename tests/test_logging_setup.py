"""Tests for partial_recall.logging_setup."""

from __future__ import annotations

import json
import sys
from io import StringIO

import structlog

from partial_recall.logging_setup import configure_logging


def test_configure_human_format_prints_readable() -> None:
    stream = StringIO()
    configure_logging(level="INFO", format="human", stream=stream)
    log = structlog.get_logger("test")
    log.info("hello", item_key="ABC123")
    output = stream.getvalue()
    assert "hello" in output
    assert "ABC123" in output


def test_configure_json_format_emits_json() -> None:
    stream = StringIO()
    configure_logging(level="INFO", format="json", stream=stream)
    log = structlog.get_logger("test")
    log.info("hello", item_key="ABC123")
    line = stream.getvalue().strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "hello"
    assert parsed["item_key"] == "ABC123"


def test_configure_logging_does_not_keep_closed_default_stderr(monkeypatch) -> None:
    original_stderr = StringIO()
    fallback_stderr = StringIO()
    monkeypatch.setattr(sys, "stderr", original_stderr)

    configure_logging(level="WARNING", format="human")

    original_stderr.close()
    monkeypatch.setattr(sys, "stderr", fallback_stderr)

    log = structlog.get_logger("test")
    log.warning("after-close")

    assert "after-close" in fallback_stderr.getvalue()


def test_invalid_format_raises_value_error() -> None:
    import pytest
    with pytest.raises(ValueError, match="format"):
        configure_logging(level="INFO", format="xml")


def test_invalid_level_raises_value_error() -> None:
    import pytest
    with pytest.raises(ValueError, match="level"):
        configure_logging(level="SCREAM", format="human")
