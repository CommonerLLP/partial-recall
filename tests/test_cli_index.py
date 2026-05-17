"""Tests for `partial-recall index` and `partial-recall status` commands."""

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
        embedding=EmbeddingConfig(),  # local-onnx + e5-small defaults
        index=IndexConfig(vector_db_path=tmp_path / "vectors.sqlite"),
        zotero=ZoteroConfig(
            sqlite_path=fixtures_dir / "zotero_snapshot" / "zotero.sqlite",
            storage_path=fixtures_dir / "zotero_snapshot" / "storage",
        ),
    )
    cfg_path = tmp_path / "config.toml"
    save_config(cfg, cfg_path)
    return cfg_path


def test_index_missing_config_errors_clearly(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["index", "--config", str(tmp_path / "nope.toml")]
    )
    assert result.exit_code != 0
    # CliRunner surfaces the raised PartialRecallError on result.exception;
    # the cli_entry wrapper that prints to stderr is exercised only outside tests.
    haystack = (
        (result.output or "")
        + (result.stderr or "")
        + str(result.exception or "")
    ).lower()
    assert "config" in haystack


def test_status_missing_db_errors_clearly(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    cfg_path = _write_minimal_config(tmp_path, fixtures_dir)
    result = runner.invoke(app, ["status", "--config", str(cfg_path)])
    assert result.exit_code != 0


@pytest.mark.slow
def test_index_then_status_smoke(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    """End-to-end smoke: index the small Zotero fixture, then check status.

    Marked @slow because it loads the real ONNX model (~470 MB, cached).
    """
    cfg_path = _write_minimal_config(tmp_path, fixtures_dir)
    # Index
    result = runner.invoke(app, ["index", "--config", str(cfg_path)])
    if result.exit_code != 0:
        print("STDOUT:", result.stdout)
        print("EXCEPTION:", result.exception)
    assert result.exit_code == 0
    assert "Indexed" in result.output

    # Status
    result = runner.invoke(app, ["status", "--config", str(cfg_path)])
    assert result.exit_code == 0
    assert "Items:" in result.output
    assert "Active run:" in result.output
