# Roadmap — partial-recall

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[/]` deferred

---

## v0.0.1 — Proof of life

**Goal:** end-to-end smoke test. Replaces the standalone `zotero_semantic_search.py` script. Usable on the user's own corpus.

**Status as of 2026-05-17: shipped** (commit `b78a9dc`).

### Scope

- [x] Package skeleton (`pyproject.toml`, `src/partial_recall/`, entry points `partial-recall` + `partial`)
- [x] Schema migration `0001_initial.sql` (7 tables; WAL mode)
- [x] `VectorStore` SQLite implementation (idempotent writes; `text_hash` dedup)
- [x] `EmbeddingProvider` Protocol + `LocalONNXProvider` (multilingual-e5-small)
- [x] `CorpusAdapter` Protocol + `ZoteroAdapter` (PDFs + abstracts only; read-only `mode=ro&immutable=1`)
- [x] PDF text extraction via `pypdf`
- [x] Chunker (recursive char 1024 / 128 overlap)
- [x] Indexing pipeline (serial; no resume yet)
- [x] MCP server (stdio only) with one tool: `semantic_search`
- [x] CLI commands: `init`, `index`, `serve`, `status`, `search`
- [x] Config (TOML + Pydantic + first-run wizard)
- [x] Secrets: env-var only (`PARTIAL_RECALL_GEMINI_API_KEY`)
- [x] Logging (structlog)
- [x] Tests: critical-path coverage (122 tests passing as of 2026-05-17)
- [x] README + first-run guide

### Out of scope (v0.1.0)

- [/] Gemini embedding provider
- [/] Resumable indexing (full implementation)
- [/] Notes / annotations / metadata-only indexing
- [/] Other MCP tools (`semantic_status`, `search_fulltext`, `get_item_details`)
- [/] Folder corpus adapter
- [/] Faiss accelerator
- [/] Doctor command (full)
- [/] Keyring secrets
- [/] HTTP transport
- [/] Cross-platform CI (macOS-only OK for v0.0.1)
- [/] Auto-generated config docs
- [/] i18n scaffolding

### Success criteria

- [x] `pipx install partial-recall` works on an Apple Silicon Mac
- [x] `partial-recall init` runs the first-run wizard; defaults to local provider; sets paths
- [x] `partial-recall index` indexes a 15k-item Zotero library end-to-end without crashing
- [x] `partial-recall serve` is reachable from Claude Code as an MCP server
- [x] `semantic_search` returns ranked results with `item_key`, score, preview, basic enriched metadata
- [ ] Disk footprint under ~1 GB for the 15k-item corpus
      <!-- Unmeasured at the v0.0.1 local-provider default (384-dim int8).
           The live index runs gemini-embedding-001 at 3072 dims, so it
           cannot answer this criterion. Measure a 15k-item local-provider
           index before ticking. -->
- [x] All tests pass on macOS

---

## v0.1.0 — First public release

**Goal:** v0.0.1 + paid-provider option + small CLI polish. First tag
the public can `pipx install`.

**Status as of 2026-05-17: shipped** (commit `3c76a22`, tag `v0.1.0`).

> **Note on scope reconciliation.** The original v0.1.0 plan promised
> "feature-complete first public release" — cross-platform CI, all four
> MCP tools, resumable indexing, multilingual fixtures, the works. What
> actually shipped is much narrower (audit 2026-05-17). Rather than
> rewrite the tag, this section now reflects what `v0.1.0` actually
> contains. The previously-planned scope has been moved to **v0.2.0 —
> Feature-complete release** below, which is what was historically
> labelled v0.1.0 in this file. Later releases renumbered accordingly.

### Adds (on top of v0.0.1)

- [x] `GeminiAPIProvider` (httpx; rate-limit with exponential backoff; retry; batch) — tests in `test_gemini_provider.py`
- [x] Metadata-only indexing for items without PDFs — `ZoteroAdapter` yields abstract source independently of PDFs
- [x] CLI flag polish: `--verbose`, `--quiet`, `--config`, `--json` (on `search`)
- [x] `[faiss]` optional dependency and `faiss_indexes` table in schema (accelerator command not yet wired)
- [x] Integration smoke test with a Zotero snapshot fixture (`tests/test_e2e_smoke.py`)
- [x] Pre-embedded vector importer (rehydrate a corpus that was embedded by another tool, skipping re-embedding cost)

### Known gaps shipped with v0.1.0 (resolved in v0.2.0)

- No CI of any kind (no `.github/workflows/`)
- Indexing is serial and non-resumable
- Notes and annotations are not indexed; ZoteroAdapter explicitly excludes them
- Only 1 of 4 planned MCP tools is implemented (`semantic_search`)
- stdio transport only; no HTTP
- No `doctor` command, no `keyring` secrets, no `vcrpy`, no Hypothesis, no log-sanitization test
- No multilingual test fixtures (English only)
- No `CITATION.cff`, no i18n scaffolding, no walkthrough/troubleshooting docs

---

## v0.2.0 — First sliceable step toward feature-complete

**Goal:** ship the essential indexing-completeness slice (Zotero notes
+ annotations + non-Zotero corpora) plus the diagnostic + safety surface
that emerged from real first-user testing. The remaining items from the
originally-planned v0.2.0 scope are now sequenced across v0.2.x
point-releases through to v0.3.0 (see those sections below).

### Adds (on top of v0.1.0)

- [x] Notes indexing in `ZoteroAdapter`
- [x] Annotations indexing in `ZoteroAdapter` (textual types: highlight, note, underline)
- [x] `FolderAdapter` (PDF/TXT/MD recursive walk; `.partial-recallignore`; EPUB/DOCX recognised but deferred)
- [x] Top-up indexing mode: `index --extend` / `--extend-run RUN_ID` / `--allow-provider-mismatch`
- [x] `doctor` command — 9 diagnostic checks (python, config, embedding provider, vector store, run-vs-config match, Zotero source, folder source, macOS UF_HIDDEN on .pth, disk space); `--json` for tooling
- [x] Indexer UX: determinate progress bar with current-item title, time-remaining estimate, plain-English explainers; pypdf noise filter with humanised end-of-run summary
- [x] PDF robustness: extractor survives malformed PDFs (missing `/Root`, mid-iter cross-reference exhaustion) — single bad PDF skips that item instead of killing the run
- [x] Log-sanitization processor: structlog records redact API-key-shaped values and absolute home paths (defence-in-depth public/private firewall)
- [x] CLI ergonomics: `partial search --limit` / `-n` as scholar-shaped alias for `--top-k` / `-k`
- [x] `CorpusAdapter` Protocol gained optional `count_items()` for determinate progress UIs (backwards-compatible default `None`)

### Known gaps shipped with v0.2.0 (sequenced into v0.2.x)

These were part of the original v0.2.0 plan. They ship in v0.2.x point-releases as separate sliceable units:

- Secrets via `keyring` (env-var fallback ships now; keyring → v0.2.x)
- Full resumable indexing (`indexing_progress` writes per-batch, SIGINT/SIGTERM/`kill -9` resume)
- CLI signal handling
- MCP tools: `semantic_status`, `search_fulltext` (FTS5), `get_item_details`
- HTTP transport stub + auth abstraction
- Faiss accelerator command (the `[faiss]` extra + table exist; build path → v0.2.x)
- Cross-platform CI matrix (macOS-14, Ubuntu-22.04, Windows-2022 × Python 3.11, 3.12)
- Property-based tests (Hypothesis) for chunker, vector packing, text_hash
- Recorded `vcrpy` cassettes for Gemini in CI
- Log-sanitization *CI-blocking* test (processor + unit tests ship now; CI gate → v0.2.x)
- Auto-generated config reference from Pydantic
- Multilingual test fixtures (10 scripts)
- i18n scaffolding (gettext `.po`)
- `CITATION.cff`
- README expansion + 5-min walkthrough + troubleshooting

### Success criteria (v0.2.0 line)

- [x] All v0.0.1 + v0.1.0 functionality still works (205 tests passing on the v0.2.0 commit)
- [x] Indexing top-up against a rehydrated Gemini corpus succeeds on a rehydrated Gemini corpus
- [x] `doctor` surfaces the cookjohn-imported → fresh-Gemini-provider mismatch as a named warning with an actionable hint
- [x] Notes + annotations indexable: `ZoteroAdapter` yields a `note` source per child note and an `annotation` source per textual annotation (types 1, 2, 5)
- [x] FolderAdapter walks a heterogeneous test corpus, respects `.partial-recallignore`, dispatches per-extension

---

## v0.2.x — point releases toward feature-complete

Each slice ships as a tagged minor (`v0.2.1`, `v0.2.2`, ...). Order is sequenced by leverage. See `docs/superpowers/specs/2026-05-18-partial-recall-v020-v030-sequencing.md` for the full plan.

### v0.2.1: reliability foundation — SHIPPED 2026-05-18
- [x] A3 recorded API fixtures (`vcrpy` + `pytest-recording`) for Gemini — infrastructure + `@pytest.mark.live` opt-in marker + scrubbing config. Cassettes themselves recorded in a follow-up once a real key is used.
- [x] A1 cross-platform CI matrix — GitHub Actions workflow at `.github/workflows/test.yml`, macOS-14 / Ubuntu-22.04 / Windows-2022 × Python 3.11, 3.12, with ruff lint + pytest (skipping slow + live) + a doctor surface-smoke on non-Windows.
- [x] A4 log-sanitization CI gate — integration test in `tests/test_logging_ci_gate.py` exercises the real structlog pipeline; caught and closed a value-shape detection gap (Gemini / GitHub / OpenAI / JWT / PEM shapes redacted regardless of field name).

### v0.2.2: resumable indexing — SHIPPED 2026-05-18
- [x] B4 `indexing_progress` writes per item, with fast-skip on resume (items at-or-below last_processed_key skipped); chunk-level vector_exists dedup remains the correctness guarantee. Progress cleared on clean completion so new items added between runs aren't accidentally skipped.
- [x] B5 SIGINT / SIGTERM handled in `run_indexing`: handler sets a flag, current batch flush completes, progress is persisted, function returns `IndexResult(interrupted=True, last_processed_key=…)` instead of raising. Signal handlers restored on exit so callers' own installations stay intact.

### v0.2.3: MCP tool surface (partial) — SHIPPED 2026-05-18
- [x] C1 `semantic_status` — returns schema_version, totals (items / chunks / vectors), corpus breakdown, active embedding-run metadata. Zero-arg tool.
- [x] C3 `get_item_details` — full metadata for a single item by `item_key` (+ optional `corpus`), with source-type breakdown and active-run vector count. Returns structured error payload (never raises) for missing item.
- [/] C2 `search_fulltext` (FTS5) deferred to v0.2.4 — needs schema migration 0002 + auto-migration support for existing DBs; bundled with v0.2.4's operability slice.

### v0.2.4: FTS5 + auto-migration + Zotero richness — SHIPPED 2026-05-19
- [x] C2 `search_fulltext` MCP tool — FTS5 virtual table mirroring chunks.text_preview (unicode61 + diacritic-fold). Supports phrase, prefix, AND/OR/NOT, corpus filter, top_k. Structured error payload on malformed query.
- [x] Auto-migration support in `store/connection.py`. Existing DBs at schema_version < CURRENT_SCHEMA_VERSION get pending migrations applied forward; future-version DBs refuse with a clear error.
- [x] Schema migration 0002 (FTS5 chunks_fts table + triggers for INSERT/DELETE/UPDATE sync).
- [x] Schema migration 0003 (Zotero richness): items gain archive / archive_location / call_number / library_catalog columns; new collections + item_collections tables with FK CASCADE.
- [x] C5 Zotero collections + library-location MCP exposure. `list_collections` tool returns corpus collections with parent_key + item_count; `get_item_details` now surfaces library_location dict + collections list.
- [x] ZoteroAdapter populates new fields from Zotero's `fields` table (archive/archiveLocation/callNumber/libraryCatalog) and yields `list_zotero_collections()` + `list_collection_memberships()`. CLI `index --source zotero` syncs both into the store before run_indexing.
- [x] D2 keyring secrets — `partial_recall.secrets` module + `partial-recall keyring {status, set-gemini, delete-gemini}` CLI. macOS Keychain / Linux Secret Service / Windows Credential Manager via the `keyring` package (optional `[keyring]` extra). GeminiAPIProvider resolves keys: keyring → env vars. Doctor reports which source the key came from.
- [/] D3 Faiss accelerator command — deferred to v0.2.5.
- [/] C4 HTTP transport stub — deferred to v0.2.5.

### Post-v0.2.4 docs sweep — landed 2026-05-19 (no version bump; docs-only)
Docs covering features already shipped through v0.2.4. No code
changes. No version bump (still v0.2.4 on main).
- [x] A5 auto-generated config reference from Pydantic. `scripts/generate_config_reference.py` walks every Pydantic model and emits `docs/config/reference.md`; the doc is the code's introspection so it cannot drift.
- [x] E3 `CITATION.cff` at repo root — standard machine-readable citation, AGPL-3.0-or-later.
- [x] E4 README expansion: extras table; install + first-run section; pointers to walkthrough + troubleshooting + config reference.
- [x] `docs/walkthrough/five-minute-walkthrough.md` — install → init → doctor → index → search → MCP-server-smoke → keyring, with expected output at each step.
- [x] `docs/troubleshooting.md` — every failure mode actually encountered in v0.2.0 → v0.2.4 development (PATH, keyring resolution order, schema-mismatch, pypdf noise, malformed PDFs, provider-mismatch on extend, iCloud UF_HIDDEN, list_collections empty, post-rewrite cached-clone divergence).

---

## v0.3.0 — Round out the text-corpus story

**Status: SHIPPED**

- [x] `MarkdownNotesAdapter` (markdown notes folders — Obsidian, The Archive, Zettlr; respects `.partial-recallignore`; parses YAML frontmatter)
- [x] `JabRefAdapter` (JabRef / BibTeX bibliography files; indexes abstracts + linked PDFs)
- [x] `CalibreAdapter` (Calibre e-book library via `metadata.db`; no Calibre install required; EPUB + PDF + TXT)
- [x] EPUB extractor (stdlib zip + html.parser; no ebooklib dep)
- [x] DOCX extractor (stdlib zip + xml.etree; no python-docx dep; for humanities scholars using Word)
- [x] `SentenceTransformerProvider` — any HuggingFace sentence-transformers model; LaBSE and BGE-M3 supported; auto CUDA/MPS/CPU detection. Language coverage per model documentation; not independently verified by partial-recall (planned v0.5.0).
- [x] Hardware-aware, language-aware init wizard — detects RAM + chip, surveys corpus languages, shows ranked model ladder with provenance (maintainer, HQ country, open-weights, license, documented military contracts, data sovereignty)
- [x] Pre-release liability disclaimer in init wizard and README
- [x] `[embedding] device = "auto"` config field (CUDA → MPS → CPU auto-detection)
- [x] `[multilingual]` pip extra (`sentence-transformers`)
- [x] Fix: Zotero collection sync used closed adapter connection
- [x] `partial-recall doctor --fix` (iCloud UF_HIDDEN fix for .pth files)

**Deferred to v0.5.0 or later:**
- [/] Locale-aware embedding routing (Tamil chunks → Tamil-strong embedder; Persian → Persian-strong)
- [/] i18n: Hindi, Tamil, Bengali, Marathi, Urdu, Swahili, Spanish, Portuguese interface strings
- [/] Better chunking: semantic-aware via `blingfire` or `spaCy`; tokenizer-aware for CJK
- [/] Snapshot / web indexing (Zotero webpage captures)
- [/] Optional Zotero plugin (triggers indexing from Zotero UI)

## v0.4.0 — Corpus correctness and SDK compatibility — SHIPPED 2026-08-20

**Breaking for anyone parsing `source_ref` on the folder corpus.** Folder refs
changed from `{index}:{rel}` to `r<hash>:{rel}`, and that value ships in MCP
output as `source.ref`. Re-run any consumer that parses folder refs. The index
migrates legacy rows in place at the next run, so no re-embedding is needed.

- [x] Stable folder root ids in `source_ref`, with in-place legacy migration (#38)
- [x] EPUB-only and DOCX-only Zotero attachments index and fetch (#44)
- [x] mcp SDK 1.x and 2.x both supported; `<2` cap lifted (#45, #40)
- [x] `partial_recall.mcp.compat.tool_input_schema` reads the Tool schema on both majors (#45)
- [x] `ALL_TOOLS` on the MCP server; one list, not two (#45)
- [x] CI matrix leg runs the suite on mcp `<2` and mcp `>=2` (#45)
- [x] `uv.lock` relocked and consistent with the manifest (#42, #46)
- [x] Stale repo names corrected in `docs/ARCHITECTURE.md` (#39)

## v0.5.0 — Multilingual for real

- [ ] Local manuscript image adapter (Tropy-compatible directory layout)
- [ ] SigLIP multimodal embeddings for figures and plates in PDFs
- [ ] Vision-LLM HTR pipeline (starts; pluggable backend)
- [ ] Tesseract integration for printed text
- [ ] Kraken integration for historical scripts (Greek, Latin, Devanagari, Arabic)
- [ ] CITATION.cff + Zenodo DOI integration

## v0.6.0 — IIIF and world manuscript archives

- [ ] IIIF Image API + Presentation API support
- [ ] Adapter for British Library digitised manuscripts
- [ ] Adapter for Bodleian Library
- [ ] Adapter for BnF (Gallica)
- [ ] Adapter for Vatican Apostolic Library (DigiVatLib)
- [ ] Adapter for Stanford, Princeton, Yale IIIF collections
- [ ] Indic / Persian-Arabic HTR models (Transkribus / community-trained)
- [ ] Manuscript-browse UX (CLI subcommand to render IIIF thumbnails to terminal where supported)

## v0.x — Scale and ecosystem

- [ ] Logseq adapter (open-source; markdown graph)
- [ ] Org-mode adapter
- [ ] Community-contributed adapters via entry points
- [ ] Mobile / iPad client via HTTP transport
- [ ] CITATION.cff publication + DOI

---

## NOT on the roadmap, deliberately

- Adapters for **closed-source** systems: Mendeley, EndNote, Paperpile, DEVONthink, Notion, Roam — not now, not ever. Project principle.
- A GUI application. CLI + MCP are the surfaces. (A separate visualisation project might emerge later from someone else.)
- Replacing Zotero. We read Zotero's data; we don't compete with Zotero's authoring/citation features.
- A built-in chat / RAG layer. The MCP client does that if the user wants it; partial-recall provides retrieval.
- A hosted SaaS product. The tool is AGPL, local-first, and will stay that way. No cloud account, no telemetry, no SaaS tier.

---

## How to read this roadmap

- Each release ships when its checklist is green AND when a real user has used it for real work.
- We do not chase a calendar. We ship when the work is ready.
- Items marked `[/]` are deliberately deferred to a later version; if you think one should be promoted, open an issue.
- This file is committed; updates go in regular commits with `chore(roadmap):` prefix.
