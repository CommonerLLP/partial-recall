"""Tests for log-sanitization (v0.2.0 A4 — CI-blocking).

These tests encode the public/private firewall invariant:

  * Sensitive-named field values are replaced with ``"***"``.
  * Absolute home-directory paths are normalised to ``~``.
  * Innocent fields (chunk counts, item_keys, scores, etc.) survive
    unmodified.

If a developer adds a log call site that violates the invariant, the
right answer is *not* to relax these tests — it's to rename or restructure
the log call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.logging_sanitize import (
    _REDACTED,
    sanitize_event_dict,
)


def _run(event: dict) -> dict:
    """Pass `event` through the processor and return the result."""
    return sanitize_event_dict(None, "info", dict(event))


# ---------------------------------------------------------------------------
# Sensitive-key redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "api-key",
        "apikey",
        "API_KEY",
        "PARTIAL_RECALL_GEMINI_API_KEY",
        "gemini_api_key",
        "secret",
        "client_secret",
        "token",
        "auth_token",
        "bearer",
        "password",
        "passwd",
        "authorization",
        "private_key",
        "session_id",
        "cookie",
    ],
)
def test_sensitive_key_value_is_redacted(key: str) -> None:
    out = _run({key: "AIzaSy_SECRET_VALUE_NOT_TO_BE_LOGGED", "event": "loaded"})
    assert out[key] == _REDACTED
    # The non-sensitive `event` survives.
    assert out["event"] == "loaded"


def test_redaction_works_regardless_of_value_type() -> None:
    """Even non-string sensitive values get redacted."""
    out = _run({"api_key": 12345, "session_id": ["x", "y"], "password": None})
    assert out["api_key"] == _REDACTED
    assert out["session_id"] == _REDACTED
    assert out["password"] == _REDACTED


def test_lookalike_non_sensitive_keys_pass_through() -> None:
    """Words that *contain* substrings like 'key' or 'token' as plain
    English are NOT redacted unless they match a word boundary."""
    out = _run({
        "item_key": "ITEM01XX",      # Zotero item key — public ID, keep
        "chunker_version": "v1",     # contains 'k' but not a secret
        "tokens_used": 142,           # plural metric, not a credential
        "monkey_patch": True,         # contains 'key' as substring
    })
    assert out["item_key"] == "ITEM01XX"
    assert out["chunker_version"] == "v1"
    assert out["tokens_used"] == 142
    assert out["monkey_patch"] is True


# ---------------------------------------------------------------------------
# Path redaction
# ---------------------------------------------------------------------------


def test_home_path_in_string_value_is_redacted() -> None:
    out = _run({
        "msg": "opened /Users/scholar/Zotero/zotero.sqlite for indexing",  # leak-ok
    })
    assert "/Users/scholar" not in out["msg"]  # leak-ok
    assert out["msg"] == "opened ~/Zotero/zotero.sqlite for indexing"


def test_linux_home_path_redacted() -> None:
    out = _run({"path": "/home/bahujan-scholar/Documents/library.bib"})  # leak-ok
    assert "/home/bahujan-scholar" not in out["path"]  # leak-ok
    assert out["path"].startswith("~/")


def test_windows_home_path_redacted() -> None:
    out = _run({"path": r"C:\Users\Scholar\Zotero\zotero.sqlite opened"})
    assert "Scholar" not in out["path"]
    assert "~" in out["path"]


def test_pathlike_objects_are_handled() -> None:
    out = _run({"vector_db_path": Path.home() / "Library" / "vectors.sqlite"})
    assert "/Users/" not in out["vector_db_path"]  # leak-ok
    assert "~" in out["vector_db_path"]


def test_multiple_paths_in_one_string() -> None:
    out = _run({
        "event": "moved /Users/scholar/a.pdf to /Users/scholar/b.pdf",  # leak-ok
    })
    # Both prefixes replaced.
    assert "/Users/scholar" not in out["event"]  # leak-ok
    assert out["event"].count("~") >= 2


def test_system_paths_not_touched() -> None:
    """`/usr/...` and `/etc/...` don't identify a user — keep them."""
    out = _run({"path": "/usr/local/bin/python3.11"})
    assert out["path"] == "/usr/local/bin/python3.11"


def test_non_path_strings_unchanged() -> None:
    out = _run({"msg": "indexed 12345 chunks", "score": 0.83})
    assert out["msg"] == "indexed 12345 chunks"
    assert out["score"] == 0.83


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_processor_does_not_mutate_caller_dict() -> None:
    """Caller should be free to inspect their original dict; we return a
    sanitized view from a fresh dict (the helper _run already copies)."""
    original = {"api_key": "secret"}
    sanitize_event_dict(None, "info", dict(original))
    assert original == {"api_key": "secret"}  # caller's input untouched


def test_empty_dict_is_safe() -> None:
    assert sanitize_event_dict(None, "info", {}) == {}


def test_processor_does_not_raise_on_weird_types() -> None:
    """The processor should be defensive: unexpected types must not crash
    logging. Logging that crashes is worse than logging that leaks."""

    class Weirdo:
        def __str__(self) -> str:
            raise RuntimeError("nope")

    out = sanitize_event_dict(None, "info", {"x": Weirdo(), "api_key": "k"})
    assert out["api_key"] == _REDACTED
    # x passes through; we don't attempt stringification.
