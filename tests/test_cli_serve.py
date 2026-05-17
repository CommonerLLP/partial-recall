"""Tests for `partial-recall serve` argument handling and pre-flight checks.

The actual MCP loop is exercised in tests/test_mcp_semantic_search.py; this
file covers the CLI's wiring: config loading, vector-DB existence checks,
active-run requirements, and signal-handler installation. We do NOT
start a real stdio MCP server in tests.
"""

from __future__ import annotations

from pathlib import Path

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


def _minimal_cfg(tmp_path: Path, fixtures_dir: Path) -> Path:
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


def test_serve_missing_config_errors_clearly(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["serve", "--config", str(tmp_path / "nope.toml")]
    )
    assert result.exit_code != 0
    # The ConfigError surfaces as an exception when invoking app directly via
    # CliRunner; the cli_entry wrapper that prints to stderr is exercised
    # outside tests.
    haystack = (
        (result.output or "")
        + (getattr(result, "stderr", "") or "")
        + str(result.exception or "")
    ).lower()
    assert "config" in haystack


def test_serve_missing_vector_db_errors_clearly(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    cfg_path = _minimal_cfg(tmp_path, fixtures_dir)
    # Vector DB doesn't exist yet (no index run)
    result = runner.invoke(app, ["serve", "--config", str(cfg_path)])
    assert result.exit_code != 0
    haystack = (
        (result.output or "")
        + (getattr(result, "stderr", "") or "")
        + str(result.exception or "")
    ).lower()
    assert "vector db" in haystack or "index" in haystack
