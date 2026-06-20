"""Tests for the CorpusAdapter registry/loader seam."""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.config.models import (
    FolderConfig,
    IndexConfig,
    PartialRecallConfig,
    ZoteroConfig,
)
from partial_recall.corpus.adapters.folder import FolderAdapter
from partial_recall.corpus.registry import BUILTIN_ADAPTER_NAMES, create_adapter
from partial_recall.errors import PartialRecallError


def _config_with_folder(tmp_path: Path) -> PartialRecallConfig:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "note.txt").write_text("hello from folder", encoding="utf-8")
    return PartialRecallConfig(
        index=IndexConfig(vector_db_path=tmp_path / "vectors.sqlite"),
        zotero=ZoteroConfig(
            enabled=False,
            sqlite_path=tmp_path / "zotero.sqlite",
            storage_path=tmp_path / "storage",
        ),
        folder=FolderConfig(enabled=True, paths=[root]),
    )


def test_registry_loads_builtin_adapter_by_name(tmp_path: Path) -> None:
    cfg = _config_with_folder(tmp_path)

    adapter = create_adapter("folder", cfg)

    assert "folder" in BUILTIN_ADAPTER_NAMES
    assert isinstance(adapter, FolderAdapter)
    assert adapter.name == "folder"
    assert [item.title for item in adapter.list_items()] == ["note"]


def test_registry_loads_external_adapter_from_dotted_import_path(
    tmp_path: Path,
) -> None:
    cfg = _config_with_folder(tmp_path)

    adapter = create_adapter(
        "tests.fixture_external_adapter:FixtureExternalAdapter",
        cfg,
    )

    item = next(adapter.list_items())
    source = next(adapter.get_sources(item))
    assert adapter.name == "fixture_external"
    assert item.corpus == "fixture_external"
    assert adapter.get_text(item, source) == "fixture external adapter text"


def test_registry_rejects_unknown_adapter_name(tmp_path: Path) -> None:
    cfg = _config_with_folder(tmp_path)

    with pytest.raises(PartialRecallError, match="dotted adapter path"):
        create_adapter("cad", cfg)
