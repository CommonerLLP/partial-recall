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

- [ ] `pipx install partial-recall` works on an Apple Silicon Mac
- [ ] `partial-recall init` runs the first-run wizard; defaults to local provider; sets paths
- [ ] `partial-recall index` indexes a 15k-item Zotero library end-to-end without crashing
- [ ] `partial-recall serve` is reachable from Claude Code as an MCP server
- [ ] `semantic_search` returns ranked results with `item_key`, score, preview, basic enriched metadata
- [ ] Disk footprint under ~1 GB for the 15k-item corpus
- [ ] All tests pass on macOS

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
> contains; the previously-planned scope has been moved to **v0.2.0 —
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

These were part of the original v0.2.0 plan; they ship in v0.2.x point-releases as separate sliceable units:

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
- [x] Notes + annotations indexable: notes and annotations enumerable in the personal corpus
- [x] FolderAdapter walks a heterogeneous test corpus, respects `.partial-recallignore`, dispatches per-extension

---

## v0.2.x — point releases toward feature-complete

Each slice ships as a tagged minor (`v0.2.1`, `v0.2.2`, ...). Order is sequenced by leverage; see `docs/superpowers/specs/2026-05-18-partial-recall-v020-v030-sequencing.md` for the full plan.

### v0.2.1: reliability foundation — SHIPPED 2026-05-18
- [x] A3 recorded API fixtures (`vcrpy` + `pytest-recording`) for Gemini — infrastructure + `@pytest.mark.live` opt-in marker + scrubbing config. Cassettes themselves recorded in a follow-up once a real key is used.
- [x] A1 cross-platform CI matrix — GitHub Actions workflow at `.github/workflows/test.yml`, macOS-14 / Ubuntu-22.04 / Windows-2022 × Python 3.11, 3.12, with ruff lint + pytest (skipping slow + live) + a doctor surface-smoke on non-Windows.
- [x] A4 log-sanitization CI gate — integration test in `tests/test_logging_ci_gate.py` exercises the real structlog pipeline; caught and closed a value-shape detection gap (Gemini / GitHub / OpenAI / JWT / PEM shapes redacted regardless of field name).

### v0.2.2: resumable indexing
- [ ] B4 full `indexing_progress` writes per batch
- [ ] B5 CLI signal handling (clean SIGINT / SIGTERM during indexing)

### v0.2.3: MCP tool surface
- [ ] C1 `semantic_status`
- [ ] C2 `search_fulltext` (FTS5 virtual table, schema migration 0002)
- [ ] C3 `get_item_details`

### v0.2.4: operability + reach
- [ ] D2 keyring secrets (macOS Keychain / Linux Secret Service / Windows Credential Manager)
- [ ] D3 Faiss accelerator command (`partial-recall runs build-faiss RUN_ID`)
- [ ] C4 HTTP transport stub (`serve --http --port N`; auth abstraction; `none` enabled)

### v0.2.5: docs, audit, citation
- [ ] A2 property-based tests (Hypothesis) for chunker + vector packing + text_hash
- [ ] A5 auto-generated config reference from Pydantic
- [ ] E1 multilingual test fixtures (10 scripts)
- [ ] E2 i18n scaffolding (gettext `.po`; English-only ship)
- [ ] E3 `CITATION.cff`
- [ ] E4 README + install docs + 5-min walkthrough script + troubleshooting page

---

## v0.3.0 — Round out the text-corpus story

- [ ] `ObsidianAdapter` (markdown files folder; link-aware; respects `.obsidian/` excludes)
- [ ] `JabRefAdapter` (open-source reference manager; BibTeX-rooted)
- [ ] `CalibreAdapter` (open-source e-book library)
- [ ] More embedding providers: Voyage-3, OpenAI text-embedding-3-small, BGE-M3 base, IndicBERT v2, MuRIL, LaBSE
- [ ] Locale-aware embedding routing (Tamil chunks → Tamil-strong embedder; Persian → Persian-strong)
- [ ] i18n shipping: Hindi, Tamil, Bengali, Marathi, Urdu, Swahili, Spanish, Portuguese
- [ ] Better chunking: semantic-aware via `blingfire` or `spaCy`; tokenizer-aware for CJK
- [ ] Snapshot / web indexing (Zotero webpage captures)
- [ ] Optional Zotero plugin (triggers indexing from Zotero UI)
- [ ] `partial-recall doctor --fix` (opt-in automatic fixes for safe issues)

## v0.4.0 — Multimodal scholarship

- [ ] Local manuscript image adapter (Tropy-compatible directory layout)
- [ ] SigLIP multimodal embeddings for figures and plates in PDFs
- [ ] Vision-LLM HTR pipeline (starts; pluggable backend)
- [ ] Tesseract integration for printed text
- [ ] Kraken integration for historical scripts (Greek, Latin, Devanagari, Arabic)
- [ ] CITATION.cff + Zenodo DOI integration

## v0.5.0 — IIIF and world manuscript archives

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
- [ ] Hosted SaaS (bring-your-own-bucket model first)
- [ ] Mobile / iPad client via HTTP transport
- [ ] CITATION.cff publication + DOI

---

## NOT on the roadmap, deliberately

- Adapters for **closed-source** systems: Mendeley, EndNote, Paperpile, DEVONthink, Notion, Roam — not now, not ever. Project principle.
- A GUI application. CLI + MCP are the surfaces. (A separate visualisation project might emerge later from someone else.)
- Replacing Zotero. We read Zotero's data; we don't compete with Zotero's authoring/citation features.
- A built-in chat / RAG layer. The MCP client does that if the user wants it; partial-recall provides retrieval.

---

## How to read this roadmap

- Each release ships when its checklist is green AND when a real user has used it for real work.
- We do not chase a calendar. We ship when the work is ready.
- Items marked `[/]` are deliberately deferred to a later version; if you think one should be promoted, open an issue.
- This file is committed; updates go in regular commits with `chore(roadmap):` prefix.
