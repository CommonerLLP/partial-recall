"""TOML I/O for partial-recall config, using tomlkit to preserve comments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from pydantic import ValidationError
from tomlkit import TOMLDocument

from partial_recall.config.models import PartialRecallConfig
from partial_recall.errors import ConfigError
from partial_recall.extract.pdf import set_pdf_backend
from partial_recall.paths import ensure_parent_directory

CONFIG_TEMPLATE = """\
# partial-recall configuration file
# https://github.com/CommonerLLP/partial-recall

config_schema_version = 1

[embedding]
provider = "local-onnx"
model = "intfloat/multilingual-e5-small"
quantization = "int8"
batch_size = 32

[index]
vector_db_path = ""
allow_external_volume = false
chunker = "recursive-char-1024-128-v1"

[zotero]
enabled = true
sqlite_path = ""
storage_path = ""

[folder]
enabled = false
paths = []

[server]
transport = "stdio"
auth_mode = "none"

[logging]
level = "INFO"
format = "human"
"""


def load_config(path: Path) -> PartialRecallConfig:
    """Load and validate config from a TOML file."""
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e}") from e
    try:
        doc = tomlkit.parse(text)
    except tomlkit.exceptions.TOMLKitError as e:
        raise ConfigError(f"cannot parse TOML in {path}: {e}") from e
    try:
        cfg = PartialRecallConfig.model_validate(_doc_to_dict(doc))
    except ValidationError as e:
        raise ConfigError(f"config validation failed in {path}:\n{e}") from e
    # Apply the PDF backend here so every entry point honours it. The five
    # adapter call sites read the process setting and need no plumbing.
    set_pdf_backend(cfg.index.pdf_backend)
    return cfg


def save_config(cfg: PartialRecallConfig, path: Path) -> None:
    """Write config to a TOML file, creating parent dirs if needed."""
    ensure_parent_directory(path)
    data = cfg.model_dump(mode="json")
    doc = tomlkit.document()
    doc.add(tomlkit.comment("partial-recall configuration file"))
    doc.add(tomlkit.comment("https://github.com/CommonerLLP/partial-recall"))
    doc.add(tomlkit.nl())
    _dict_to_doc(data, doc)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _doc_to_dict(doc: TOMLDocument) -> dict[str, Any]:
    """Convert tomlkit document to plain dict (recursively) for Pydantic validation."""
    result = _unwrap(doc)
    assert isinstance(result, dict)
    return result


def _unwrap(obj: Any) -> Any:
    """Recursively unwrap tomlkit container types into plain dict/list/scalar.

    Typed as Any -> Any because tomlkit's container types are too varied
    (Table, InlineTable, Array, Integer, String, Bool, etc.) to enumerate
    in a meaningful Union; the Pydantic validator downstream is the real
    type gate.
    """
    if isinstance(obj, dict):
        return {k: _unwrap(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unwrap(v) for v in obj]
    return obj


def _dict_to_doc(data: dict[str, Any], doc: TOMLDocument) -> None:
    """Populate a TOML document from a plain dict, splitting into sections."""
    scalars: dict[str, Any] = {}
    sections: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            sections[k] = v
        else:
            scalars[k] = v
    for k, v in scalars.items():
        doc[k] = v
    for name, section in sections.items():
        table = tomlkit.table()
        for k, v in section.items():
            if v is None:
                continue  # tomlkit doesn't represent None; skip
            table[k] = v
        doc[name] = table
