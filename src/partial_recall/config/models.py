"""Pydantic schemas for partial-recall configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Known values — kept narrow in v0.0.1; expanded as providers/adapters are added.
EmbeddingProviderName = Literal["local-onnx", "gemini", "sentence-transformer"]
QuantizationName = Literal["int8", "float16", "float32"]
ServerTransport = Literal["stdio", "http"]
ServerAuthMode = Literal["none", "token", "oauth"]
LoggingFormat = Literal["human", "json"]
LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    provider: EmbeddingProviderName = "local-onnx"
    model: str = "intfloat/multilingual-e5-small"
    quantization: QuantizationName = "int8"
    batch_size: int = Field(default=32, ge=1, le=512)
    max_input_tokens: int = Field(default=512, ge=64, le=8192)
    device: str = "auto"  # "auto" | "cpu" | "cuda" | "mps"


class IndexConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vector_db_path: Path
    allow_external_volume: bool = False
    chunker: str = "recursive-char-1024-128-v1"
    chunk_size: int = Field(default=1024, ge=128, le=8192)
    chunk_overlap: int = Field(default=128, ge=0, le=1024)


class ZoteroConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    sqlite_path: Path
    storage_path: Path
    api_key: str | None = None
    user_id: str | None = None
    group_id: str | None = None


class FolderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    paths: list[Path] = Field(default_factory=list)
    recursive: bool = True
    extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".epub", ".txt", ".md", ".docx"]
    )


class MarkdownNotesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    notes_path: Path | None = None


class JabRefConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    bib_path: Path | None = None


class CalibreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    library_path: Path | None = None


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: ServerTransport = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = Field(default=8765, ge=1, le=65535)
    auth_mode: ServerAuthMode = "none"


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: LoggingLevel = "INFO"
    format: LoggingFormat = "human"
    file_path: Path | None = None


class PartialRecallConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_schema_version: int = 1
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    index: IndexConfig
    zotero: ZoteroConfig
    folder: FolderConfig = Field(default_factory=FolderConfig)
    markdown_notes: MarkdownNotesConfig = Field(default_factory=MarkdownNotesConfig)
    jabref: JabRefConfig = Field(default_factory=JabRefConfig)
    calibre: CalibreConfig = Field(default_factory=CalibreConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
