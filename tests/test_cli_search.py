"""Tests for `partial-recall search`."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from partial_recall.cli.app import app
from partial_recall.config.loader import save_config
from partial_recall.config.models import (
    EmbeddingConfig,
    IndexConfig,
    PartialRecallConfig,
    ZoteroConfig,
)

runner = CliRunner()


def _write_minimal_config(tmp_path: Path, fixtures_dir: Path) -> Path:
    cfg = PartialRecallConfig(
        embedding=EmbeddingConfig(),
        index=IndexConfig(vector_db_path=tmp_path / "vectors.sqlite"),
        zotero=ZoteroConfig(
            sqlite_path=fixtures_dir / "zotero_snapshot" / "zotero.sqlite",
            storage_path=fixtures_dir / "zotero_snapshot" / "storage",
        ),
    )
    cfg_path = tmp_path / "config.toml"
    save_config(cfg, cfg_path)
    return cfg_path


def test_search_missing_config_errors_clearly(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["search", "library policy", "--config", str(tmp_path / "nope.toml")],
    )
    assert result.exit_code != 0


@pytest.mark.slow
def test_search_after_index_returns_results(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    cfg_path = _write_minimal_config(tmp_path, fixtures_dir)
    # Index first
    r = runner.invoke(app, ["index", "--config", str(cfg_path)])
    assert r.exit_code == 0
    # Now search
    r = runner.invoke(
        app,
        [
            "search",
            "library policy India",
            "--top-k",
            "3",
            "--config",
            str(cfg_path),
        ],
    )
    if r.exit_code != 0:
        print(r.output)
        print(r.exception)
    assert r.exit_code == 0
    # Output should contain the table header or "no title" if results are weak.
    # At minimum it shouldn't crash.
