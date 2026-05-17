"""Shared pytest fixtures for partial-recall tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests that download models or otherwise take >1s"
    )


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
