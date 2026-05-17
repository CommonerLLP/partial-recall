# Roadmap — partial-recall

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[/]` deferred

---

## v0.0.1 — Proof of life

**Goal:** end-to-end smoke test. Replaces the standalone `zotero_semantic_search.py` script. Usable on the user's own corpus.

### Scope

- [ ] Package skeleton (`pyproject.toml`, `src/partial_recall/`, entry points)
- [ ] Schema migration `0001_initial.sql` (7 tables; WAL mode)
- [ ] `VectorStore` SQLite implementation (idempotent writes; `text_hash` dedup)
- [ ] `EmbeddingProvider` Protocol + `LocalONNXProvider` (multilingual-e5-small)
- [ ] `CorpusAdapter` Protocol + `ZoteroAdapter` (PDFs + abstracts only; read-only `mode=ro&immutable=1`)
- [ ] PDF text extraction via `pypdf`
- [ ] Chunker (recursive char 1024 / 128 overlap; chunker_version = `recursive-char-1024-128-v1`)
- [ ] Indexing pipeline (serial; no resume yet)
- [ ] MCP server (stdio only) with one tool: `semantic_search`
- [ ] CLI commands: `init`, `index`, `serve`, `status`, `search`
- [ ] Config (TOML + Pydantic + first-run wizard)
- [ ] Secrets: env-var only (`PARTIAL_RECALL_GEMINI_API_KEY`; not used in v0.0.1 since Gemini deferred)
- [ ] Logging (structlog)
- [ ] Tests: critical-path coverage (vector store roundtrip, embedding provider, search end-to-end)
- [ ] README + first-run guide

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

## v0.1.0 — Feature-complete first public release

**Goal:** ship-ready. Honors the full audience. Cross-platform. All four tools. Resumable. Tested.

### Adds (on top of v0.0.1)

- [ ] `GeminiAPIProvider` (httpx; rate-limit with exponential backoff; retry; batch)
- [ ] Secrets via `keyring` (macOS Keychain / Linux Secret Service / Windows Credential Manager) with env-var fallback
- [ ] Resumable indexing (full `indexing_progress` implementation; handles SIGINT/SIGTERM/network drop/kill -9)
- [ ] Notes indexing in `ZoteroAdapter`
- [ ] Annotations indexing in `ZoteroAdapter`
- [ ] Metadata-only indexing for items without PDFs
- [ ] `FolderAdapter` (PDF/EPUB/TXT/MD/DOCX; recursive; `.partial-recallignore` support)
- [ ] MCP tool: `semantic_status`
- [ ] MCP tool: `search_fulltext` (FTS5 virtual table)
- [ ] MCP tool: `get_item_details`
- [ ] Faiss optional accelerator (behind `[faiss]` extra; `partial-recall runs build-faiss RUN_ID`)
- [ ] Full `doctor` command (capability audit; structured report)
- [ ] CLI polish: `--verbose`, `--json`, `--quiet`, `--config`, signal handling
- [ ] HTTP transport mode (`partial-recall serve --http --port N`; auth abstraction shipped, `none` only enabled)
- [ ] Multilingual test fixtures: English, Hindi, Tamil, Bengali, Persian, Arabic, Hebrew, Swahili, Spanish, Mandarin
- [ ] Integration tests with golden Zotero snapshot
- [ ] Cross-platform CI: GitHub Actions matrix (macOS-14, Ubuntu-22.04, Windows-2022) × (Python 3.11, 3.12)
- [ ] Property-based tests (Hypothesis) for chunker + vector packing + text_hash stability
- [ ] Recorded API fixtures (`vcrpy`) for Gemini — zero live API calls in CI
- [ ] Log-sanitization test (CI-blocking)
- [ ] Auto-generated config reference from Pydantic
- [ ] i18n scaffolding (gettext `.po` infrastructure; English-only ship)
- [ ] `CITATION.cff` for scholars who cite the tool
- [ ] README + install docs + 5-min walkthrough script + troubleshooting

### Success criteria

- [ ] All v0.0.1 criteria still pass
- [ ] Scholar on a 4 GB Windows 11 laptop can install + index 500 PDFs + serve via MCP
- [ ] Scholar on a 4 GB Linux laptop (no desktop environment) can install + index + use the CLI directly
- [ ] All 4 MCP tools return well-formed JSON-RPC responses
- [ ] Indexing resumes correctly after `kill -9`, network drop mid-batch, OS restart
- [ ] CI green on macOS, Linux, Windows
- [ ] Doctor command catches every documented failure mode with an actionable hint
- [ ] No raw Python tracebacks shown to user; all errors typed and explained
- [ ] 85% line coverage on `src/partial_recall/` (excluding `__main__.py` and CLI argument-parsing)
- [ ] README, install docs, walkthrough video script, troubleshooting page all published

---

## v0.2.0 — Round out the text-corpus story

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

## v0.3.0 — Multimodal scholarship

- [ ] Local manuscript image adapter (Tropy-compatible directory layout)
- [ ] SigLIP multimodal embeddings for figures and plates in PDFs
- [ ] Vision-LLM HTR pipeline (starts; pluggable backend)
- [ ] Tesseract integration for printed text
- [ ] Kraken integration for historical scripts (Greek, Latin, Devanagari, Arabic)
- [ ] CITATION.cff + Zenodo DOI integration

## v0.4.0 — IIIF and world manuscript archives

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
