# Configuration reference

Generated from the Pydantic models in `src/partial_recall/config/models.py` by `scripts/generate_config_reference.py`. Edit the model field descriptions, not this file.

The config lives at the platform's user-config dir (see `partial-recall doctor` for the path on your system). It's a TOML file with one `[section]` per Pydantic model.

## Top-level

| field | type | default | description |
|---|---|---|---|
| `config_schema_version` | `int` | `1` | Increments when the config-file schema changes in a backward-incompatible way. v0.2.x = 1. |

## `[embedding]`

Which embedding provider produces vectors, which model, batch shape.

| field | type | default | description |
|---|---|---|---|
| `provider` | `Literal` | `"local-onnx"` |  |
| `model` | `str` | `"intfloat/multilingual-e5-small"` |  |
| `quantization` | `Literal` | `"int8"` |  |
| `batch_size` | `int` | `32` |  |
| `max_input_tokens` | `int` | `512` |  |

## `[index]`

Where the SQLite vector store lives + chunking parameters.

| field | type | default | description |
|---|---|---|---|
| `vector_db_path` | `Path` | `PydanticUndefined` |  |
| `allow_external_volume` | `bool` | `false` |  |
| `chunker` | `str` | `"recursive-char-1024-128-v1"` |  |
| `chunk_size` | `int` | `1024` |  |
| `chunk_overlap` | `int` | `128` |  |

## `[zotero]`

Pointer to a Zotero library; how to read it.

| field | type | default | description |
|---|---|---|---|
| `enabled` | `bool` | `true` |  |
| `sqlite_path` | `Path` | `PydanticUndefined` |  |
| `storage_path` | `Path` | `PydanticUndefined` |  |

## `[folder]`

Optional non-Zotero corpus: a directory tree of documents.

| field | type | default | description |
|---|---|---|---|
| `enabled` | `bool` | `false` |  |
| `paths` | `list` | `[]` |  |
| `recursive` | `bool` | `true` |  |
| `extensions` | `list` | `[`'.pdf'`, `'.epub'`, `'.txt'`, `'.md'`, `'.docx'`]` |  |

## `[server]`

MCP server transport + auth mode.

| field | type | default | description |
|---|---|---|---|
| `transport` | `Literal` | `"stdio"` |  |
| `http_host` | `str` | `"127.0.0.1"` |  |
| `http_port` | `int` | `8765` |  |
| `auth_mode` | `Literal` | `"none"` |  |

## `[logging]`

Log level + output format.

| field | type | default | description |
|---|---|---|---|
| `level` | `Literal` | `"INFO"` |  |
| `format` | `Literal` | `"human"` |  |
| `file_path` | `pathlib.Path | None` | _unset_ |  |

