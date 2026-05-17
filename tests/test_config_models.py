"""Tests for partial_recall.config.models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from partial_recall.config.models import (
    EmbeddingConfig,
    FolderConfig,
    IndexConfig,
    LoggingConfig,
    PartialRecallConfig,
    ServerConfig,
    ZoteroConfig,
)


def test_embedding_config_defaults() -> None:
    cfg = EmbeddingConfig()
    assert cfg.provider == "local-onnx"
    assert cfg.model == "intfloat/multilingual-e5-small"
    assert cfg.quantization == "int8"
    assert cfg.batch_size == 32


def test_embedding_config_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        EmbeddingConfig(provider="unknown-provider-xyz")


def test_embedding_config_rejects_unknown_quantization() -> None:
    with pytest.raises(ValidationError):
        EmbeddingConfig(quantization="fp64")


def test_zotero_config_requires_paths(tmp_path: Path) -> None:
    cfg = ZoteroConfig(
        sqlite_path=tmp_path / "zotero.sqlite",
        storage_path=tmp_path / "storage",
    )
    assert cfg.enabled is True


def test_full_config_with_required_index_and_zotero(tmp_path: Path) -> None:
    cfg = PartialRecallConfig(
        index=IndexConfig(vector_db_path=tmp_path / "vectors.sqlite"),
        zotero=ZoteroConfig(
            sqlite_path=tmp_path / "zotero.sqlite",
            storage_path=tmp_path / "storage",
        ),
    )
    assert cfg.config_schema_version == 1
    assert cfg.embedding.provider == "local-onnx"
    assert cfg.server.transport == "stdio"


def test_server_config_rejects_unknown_auth_mode() -> None:
    with pytest.raises(ValidationError):
        ServerConfig(auth_mode="bearer-jwt")


def test_folder_config_default_extensions_includes_pdf() -> None:
    fc = FolderConfig()
    assert ".pdf" in fc.extensions


def test_logging_config_rejects_unknown_format() -> None:
    with pytest.raises(ValidationError):
        LoggingConfig(format="xml")
