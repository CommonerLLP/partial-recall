"""Tests for `partial-recall place`."""

from __future__ import annotations

import json
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

@pytest.mark.slow
def test_place_after_index(tmp_path: Path, fixtures_dir: Path) -> None:
    cfg_path = _write_minimal_config(tmp_path, fixtures_dir)
    # Index first
    r = runner.invoke(app, ["index", "--config", str(cfg_path)])
    assert r.exit_code == 0

    # Test an owned title
    r = runner.invoke(
        app,
        [
            "place",
            "--title",
            "The library policy of India has evolved significantly since 1947.",
            "--corpus",
            "zotero",
            "--json",
            "--config",
            str(cfg_path),
        ],
    )
    assert r.exit_code == 0
    data = json.loads(r.output[r.output.find("{"):])
    assert data["placement"]["density"] == "dense"
    assert "query_text" in data
    assert "interpretation" in data
    assert "neighbours" in data

    # Test a novel title
    r = runner.invoke(
        app,
        [
            "place",
            "--title",
            "Quantum Mechanics and General Relativity Unification",
            "--json",
            "--config",
            str(cfg_path),
        ],
    )
    assert r.exit_code == 0
    data = json.loads(r.output[r.output.find("{"):])
    assert data["placement"]["likely_owned"] is False
    assert data["placement"]["density"] in ("empty", "thin")
