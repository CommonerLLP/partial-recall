"""Shared pytest fixtures for partial-recall tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests that download models or otherwise take >1s"
    )
    config.addinivalue_line(
        "markers",
        "live: marks tests that hit a real external API (Gemini, etc.). "
        "Skipped by default; opt in with `pytest --run-live`. Use only to "
        "RECORD new vcrpy cassettes — never in CI.",
    )


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run @pytest.mark.live tests (real external API calls). "
             "Use only to record new cassettes — never in CI.",
    )


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.live tests unless --run-live is given."""
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(
        reason="skipped — pass --run-live to hit real external APIs"
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


# ---------------------------------------------------------------------------
# vcrpy / pytest-recording configuration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vcr_config() -> dict:
    """pytest-recording configuration.

    * cassettes live under tests/fixtures/cassettes/ (one file per test)
    * any `key=` query parameter is scrubbed before write (Gemini puts
      the API key in the URL)
    * Authorization / x-goog-api-key headers are scrubbed
    * request matching does NOT use the key (so cassettes replay even
      when no key is set)
    * default record_mode='none' → CI never records and never makes
      live calls; recording is opt-in via `--record-mode=once --run-live`.
    """
    return {
        "cassette_library_dir": str(
            Path(__file__).parent / "fixtures" / "cassettes"
        ),
        "filter_query_parameters": [("key", "REDACTED")],
        "filter_headers": [
            ("authorization", "REDACTED"),
            ("x-goog-api-key", "REDACTED"),
            ("cookie", "REDACTED"),
        ],
        "match_on": ["method", "scheme", "host", "port", "path"],
        "record_mode": "none",
    }


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Per-test temporary directory for partial-recall data (config, vectors, etc.)."""
    d = tmp_path / "partial-recall-data"
    d.mkdir()
    return d


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to tests/fixtures/."""
    return Path(__file__).parent / "fixtures"
