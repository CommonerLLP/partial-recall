"""Tests for `partial-recall import cookjohn`."""

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
from partial_recall.store.vector_store import VectorStore

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


def test_import_cookjohn_missing_source_errors(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    cfg_path = _minimal_cfg(tmp_path, fixtures_dir)
    result = runner.invoke(
        app,
        [
            "import",
            "cookjohn",
            "--source",
            str(tmp_path / "nope.sqlite"),
            "--config",
            str(cfg_path),
        ],
    )
    assert result.exit_code != 0
    combined = (result.output + str(result.exception or "")).lower()
    assert "not found" in combined


def test_import_cookjohn_happy_path(tmp_path: Path, fixtures_dir: Path) -> None:
    cfg_path = _minimal_cfg(tmp_path, fixtures_dir)
    source = fixtures_dir / "cookjohn_snapshot" / "zotero-mcp-vectors.sqlite"
    result = runner.invoke(
        app,
        [
            "import",
            "cookjohn",
            "--source",
            str(source),
            "--config",
            str(cfg_path),
            "--yes",
        ],
    )
    if result.exit_code != 0:
        print("STDOUT:", result.stdout)
        print("EXCEPTION:", result.exception)
    assert result.exit_code == 0
    assert "Items imported" in result.output
    assert "Vectors written" in result.output

    # Verify the run is active
    store = VectorStore(tmp_path / "vectors.sqlite")
    active = store.get_active_run()
    assert active is not None
    assert active.provider == "cookjohn-imported"
    assert active.dimensions == 3072
    store.close()


def test_import_cookjohn_no_activate(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    cfg_path = _minimal_cfg(tmp_path, fixtures_dir)
    source = fixtures_dir / "cookjohn_snapshot" / "zotero-mcp-vectors.sqlite"
    result = runner.invoke(
        app,
        [
            "import",
            "cookjohn",
            "--source",
            str(source),
            "--config",
            str(cfg_path),
            "--no-activate",
        ],
    )
    assert result.exit_code == 0
    store = VectorStore(tmp_path / "vectors.sqlite")
    active = store.get_active_run()
    assert active is None  # No run activated
    runs = store.list_runs()
    assert len(runs) == 1  # But the run was created
    store.close()
