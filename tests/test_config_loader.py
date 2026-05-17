"""Tests for partial_recall.config.loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.config.loader import (
    CONFIG_TEMPLATE,
    load_config,
    save_config,
)
from partial_recall.config.models import (
    IndexConfig,
    PartialRecallConfig,
    ZoteroConfig,
)
from partial_recall.errors import ConfigError


def _minimal_cfg(tmp_path: Path) -> PartialRecallConfig:
    return PartialRecallConfig(
        index=IndexConfig(vector_db_path=tmp_path / "vectors.sqlite"),
        zotero=ZoteroConfig(
            sqlite_path=tmp_path / "zotero.sqlite",
            storage_path=tmp_path / "storage",
        ),
    )


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    cfg = _minimal_cfg(tmp_path)
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.index.vector_db_path == cfg.index.vector_db_path
    assert loaded.zotero.sqlite_path == cfg.zotero.sqlite_path
    assert loaded.embedding.provider == "local-onnx"


def test_save_writes_a_toml_file_with_section_headers(tmp_path: Path) -> None:
    cfg = _minimal_cfg(tmp_path)
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    content = path.read_text(encoding="utf-8")
    assert "[embedding]" in content
    assert "[zotero]" in content
    assert "[index]" in content


def test_load_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nonexistent.toml")


def test_load_malformed_toml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("this is = = = bad toml [[", encoding="utf-8")
    with pytest.raises(ConfigError, match="parse"):
        load_config(path)


def test_load_invalid_schema_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "wrong.toml"
    path.write_text(
        '[embedding]\nprovider = "unknown-provider"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    cfg = _minimal_cfg(tmp_path)
    nested = tmp_path / "a" / "b" / "config.toml"
    save_config(cfg, nested)
    assert nested.exists()


def test_config_template_contains_section_headers() -> None:
    assert "[embedding]" in CONFIG_TEMPLATE
    assert "[zotero]" in CONFIG_TEMPLATE
