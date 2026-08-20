# Configuration reference

Generated from the Pydantic models in `src/partial_recall/config/models.py`.
The config lives at the platform's user-config dir (see `partial-recall doctor`
for the path on your system). It is a TOML file with one `[section]` per model.

## Top-level

| field | type | default | description |
|---|---|---|---|
| `config_schema_version` | `int` | `1` | Increments when the config-file schema changes in a backward-incompatible way. v0.2.x–v0.3.x = 1. |

## `[embedding]`

Which embedding provider produces vectors, which model, batch shape, and device.

| field | type | default | description |
|---|---|---|---|
| `provider` | `"local-onnx" \| "gemini" \| "sentence-transformer"` | `"local-onnx"` | Embedding backend. `local-onnx` = default ONNX model, CPU-only. `sentence-transformer` = any HuggingFace sentence-transformers model with CUDA/Metal auto-detection. `gemini` = Google cloud API (data leaves your machine). |
| `model` | `str` | `"intfloat/multilingual-e5-small"` | HuggingFace model ID or Gemini model name. |
| `quantization` | `"int8" \| "float16" \| "float32"` | `"int8"` | Vector quantization. int8 halves storage with minimal recall loss. |
| `batch_size` | `int` | `32` | Chunks per embedding batch. Lower if you hit OOM on a small machine. |
| `max_input_tokens` | `int` | `512` | Truncate chunks longer than this before embedding. |
| `device` | `str` | `"auto"` | Compute device for `sentence-transformer` provider. `"auto"` detects CUDA → MPS → CPU in that order. Set `"cpu"` to force CPU; `"cuda"` or `"mps"` to force a specific backend. Ignored by `local-onnx` and `gemini`. |

### Recommended models by corpus language

| your corpus | recommended model | provider | RAM needed |
|---|---|---|---|
| Primarily Latin-script (English, French, German…) | `intfloat/multilingual-e5-small` | `local-onnx` | ~1 GB |
| South Asian scripts (Tamil, Malayalam, Bengali, Urdu, Hindi…) | `sentence-transformers/LaBSE` | `sentence-transformer` | ~2.5 GB |
| Mixed multilingual / highest quality | `BAAI/bge-m3` | `sentence-transformer` | ~3.5 GB |
| No hardware constraints, willing to use cloud | `gemini-embedding-001` | `gemini` | none (API) |

**Note on multilingual coverage:** LaBSE and BGE-M3 are designed for South Asian and Arabic scripts per their model documentation. Retrieval quality across Tamil, Hindi, Bengali, Urdu, Persian, and Arabic has not yet been independently verified by partial-recall. Independent verification is planned for v0.5.0.

For `sentence-transformer` models, install the `multilingual` extra first:
```bash
pipx inject partial-recall sentence-transformers
```

## `[index]`

Where the SQLite vector store lives + chunking parameters.

| field | type | default | description |
|---|---|---|---|
| `vector_db_path` | `Path` | **required** | Path to the SQLite vector DB file. Created on first `index` run. |
| `allow_external_volume` | `bool` | `false` | Suppress the external-volume warning. |
| `chunker` | `str` | `"recursive-char-1024-128-v1"` | Chunker ID. Currently only `recursive-char-*` is supported. |
| `chunk_size` | `int` | `1024` | Characters per chunk. |
| `chunk_overlap` | `int` | `128` | Character overlap between consecutive chunks. |

## `[zotero]`

Pointer to a Zotero library. Required if `--source zotero`.

| field | type | default | description |
|---|---|---|---|
| `enabled` | `bool` | `true` | Set `false` to skip this source. |
| `sqlite_path` | `Path` | **required** | Path to `zotero.sqlite`. Usually `~/Zotero/zotero.sqlite`. |
| `storage_path` | `Path` | **required** | Path to Zotero's `storage/` directory. Usually `~/Zotero/storage`. |

## `[folder]`

Index a directory tree of documents (PDFs, EPUBs, DOCX, plain text, Markdown).

| field | type | default | description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Must be `true` to use `--source folder`. |
| `paths` | `list[Path]` | `[]` | One or more root directories to walk. |
| `recursive` | `bool` | `true` | Walk subdirectories. Set `false` to index only the top level. |
| `extensions` | `list[str]` | `[".pdf", ".epub", ".txt", ".md", ".docx"]` | File extensions to index. |

## `[markdown_notes]`

Index a folder of Markdown notes (Obsidian, The Archive, Zettlr, or any
directory of `.md` files).

| field | type | default | description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Must be `true` to use `--source markdown_notes`. |
| `notes_path` | `Path \| None` | _unset_ | Path to the notes folder. Respects `.partial-recallignore`. |

## `[jabref]`

Index a JabRef / BibTeX bibliography file (`.bib`). Indexes abstracts and
linked PDFs. Requires `bibtexparser` (`pipx inject partial-recall bibtexparser`).

| field | type | default | description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Must be `true` to use `--source jabref`. |
| `bib_path` | `Path \| None` | _unset_ | Path to the `.bib` file. |

## `[calibre]`

Index a Calibre e-book library. Reads `metadata.db` directly — no Calibre
installation needed. Indexes EPUB, PDF, and TXT books.

| field | type | default | description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Must be `true` to use `--source calibre`. |
| `library_path` | `Path \| None` | _unset_ | Path to the Calibre library folder (the one containing `metadata.db`). |

## `[server]`

MCP server transport + auth mode.

| field | type | default | description |
|---|---|---|---|
| `transport` | `"stdio" \| "http"` | `"stdio"` | `stdio` is the standard for MCP clients (Claude Code, Claude Desktop). `http` is a stub for future SaaS use. |
| `http_host` | `str` | `"127.0.0.1"` | Bind address for HTTP transport. |
| `http_port` | `int` | `8765` | Port for HTTP transport. |
| `auth_mode` | `"none" \| "token" \| "oauth"` | `"none"` | Auth for HTTP transport. Ignored for stdio. |

## `[logging]`

Log level + output format.

| field | type | default | description |
|---|---|---|---|
| `level` | `"DEBUG" \| "INFO" \| "WARNING" \| "ERROR" \| "CRITICAL"` | `"INFO"` | Minimum log level. |
| `format` | `"human" \| "json"` | `"human"` | `human` = readable coloured output. `json` = structured logs for log aggregators. |
| `file_path` | `Path \| None` | _unset_ | Write logs to this file in addition to stderr. |

## Full example `config.toml`

```toml
config_schema_version = 1

[embedding]
provider = "sentence-transformer"
model = "sentence-transformers/LaBSE"
device = "auto"
batch_size = 32

[index]
vector_db_path = "/home/researcher/.local/share/partial-recall/vectors.sqlite"

[zotero]
enabled = true
sqlite_path = "/home/researcher/Zotero/zotero.sqlite"
storage_path = "/home/researcher/Zotero/storage"

[folder]
enabled = true
paths = ["/home/researcher/Documents/papers", "/home/researcher/Downloads/theses"]
extensions = [".pdf", ".epub", ".docx"]

[markdown_notes]
enabled = true
notes_path = "/home/researcher/Notes"

[calibre]
enabled = false
library_path = "/home/researcher/Calibre Library"

[server]
transport = "stdio"

[logging]
level = "INFO"
format = "human"
```
