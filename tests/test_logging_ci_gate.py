"""End-to-end log-sanitization CI gate (v0.2.1 A4).

The unit tests in `test_logging_sanitize.py` exercise the processor in
isolation. This file is the *integration* gate: it boots the real
structlog configuration and pushes representative log records through
it, then asserts that no rendered output contains anything that
shouldn't ship.

If a future change adds a new log call site that violates the public/
private firewall (e.g. logs an api_key field with a real value, or
prints a full home-directory path in event text), this test fails CI
and the PR cannot land.

Categories asserted absent in the rendered output:

  1. Gemini-style API keys (AIzaSy… 39-char shape).
  2. Generic-shaped sensitive values logged under sensitive-named
     keys (api_key, token, secret, password, authorization, bearer,
     session_id, cookie, private_key).
  3. macOS / Linux / Windows home-directory paths
     (/Users/<name>, /home/<name>, C:\\Users\\<name>).

The test runs once per output format (human + json).
"""

from __future__ import annotations

import io
import json
import re

import pytest
import structlog

from partial_recall.logging_setup import configure_logging

# Plausible-shape Gemini key: prefix + 33 chars to hit the 39-char total.
_FAKE_GEMINI_KEY = "AIzaSy" + "X" * 33
_SENSITIVE_VALUES = {
    "AIzaSy_KEY": _FAKE_GEMINI_KEY,
    "token":      "ghp_" + "Z" * 36,
    "password":   "hunter2-with-extra-chars",
    "secret":     "sk-test-do-not-leak-1234567890",
    "bearer":     "eyJleHAtbnVtYmVyLWp3dC1zaWctaGVyZQ==",
    "session_id": "sess_8a3d2f1c5e7b9d0a4c6e8f1a3b5d7c9e",
    "cookie":     "auth=abcd-efgh-ijkl-mnop; HttpOnly",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQ...\n-----END",
}
_HOME_PATHS = [
    "/Users/aakash/Library/Application Support/partial-recall/vectors.sqlite",
    "/home/scholar/Documents/library.bib",
    r"C:\Users\Aakash\Zotero\zotero.sqlite",
]


def _drain_streams(level: str, format: str) -> str:
    """Configure logging into a buffer, emit dangerous records, return rendered text."""
    buf = io.StringIO()
    configure_logging(level=level, format=format, stream=buf)
    log = structlog.get_logger("partial_recall.test")

    # 1. A sensitive-named field with a sensitive value.
    for key, val in _SENSITIVE_VALUES.items():
        log.info("test.sensitive_field", **{key: val})

    # 2. A home path in a free-text field (event string) — the processor
    #    rewrites string VALUES, including event text since structlog
    #    treats `event` as just another field.
    for path in _HOME_PATHS:
        log.info("test.home_path_in_event", path=path, msg=f"opened {path}")

    # 3. Mixed: sensitive value + path in same record.
    log.info(
        "test.combined",
        api_key=_FAKE_GEMINI_KEY,
        msg="loading /Users/aakash/.config/partial-recall/config.toml",
    )

    return buf.getvalue()


def _assert_no_leaks(text: str, format: str) -> None:
    """Raise if any of the dangerous values survives in `text`."""
    # 1. Sensitive values, by exact substring.
    for label, val in _SENSITIVE_VALUES.items():
        assert val not in text, (
            f"[{format}] sensitive value labelled {label!r} leaked into log "
            f"output (value: {val!r})"
        )
    # 2. Home paths, by exact prefix.
    for path in _HOME_PATHS:
        # The path may have been normalised to "~" — that's fine. What
        # must not appear is the original full path that identifies the
        # user.
        assert path not in text, (
            f"[{format}] home path {path!r} leaked into log output"
        )
    # 3. Gemini-shape regex as a belt-and-braces final sweep.
    gemini_re = re.compile(r"AIzaSy[A-Za-z0-9_\-]{30,}")
    leaked = gemini_re.findall(text)
    assert not leaked, (
        f"[{format}] Gemini-shape API key(s) survived sanitization: {leaked!r}"
    )


@pytest.mark.parametrize("fmt", ["human", "json"])
def test_log_pipeline_redacts_sensitive_fields_and_paths(fmt: str) -> None:
    """The CI gate: dangerous values in, no dangerous values out."""
    rendered = _drain_streams(level="INFO", format=fmt)
    assert rendered, f"[{fmt}] expected log output but stream was empty"
    _assert_no_leaks(rendered, fmt)


def test_json_output_redacts_under_each_field_name() -> None:
    """JSON renderer keeps field names; verify each known-sensitive key
    resolves to the redaction sentinel, not to the leaked value."""
    rendered = _drain_streams(level="INFO", format="json")
    for raw_line in rendered.strip().splitlines():
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        for key in payload:
            kl = key.lower()
            if any(
                sub in kl for sub in (
                    "api_key", "apikey", "token", "secret", "password",
                    "authorization", "bearer", "session_id", "cookie",
                    "private_key",
                )
            ):
                assert payload[key] == "***", (
                    f"sensitive key {key!r} should be redacted to '***'; "
                    f"got {payload[key]!r}"
                )


def test_processor_is_actually_installed_in_chain() -> None:
    """Defensive: make sure `sanitize_event_dict` is part of the
    configured processor chain. If a future refactor accidentally drops
    it, this fails before any leak gets a chance to ship."""
    configure_logging(level="INFO", format="human")
    # structlog stores its config in a module-level state; pull it back.
    cfg = structlog.get_config()
    processor_names = [
        getattr(p, "__name__", type(p).__name__) for p in cfg["processors"]
    ]
    assert "sanitize_event_dict" in processor_names, (
        "Log-sanitization processor missing from structlog chain. Check "
        "partial_recall.logging_setup.configure_logging."
    )
