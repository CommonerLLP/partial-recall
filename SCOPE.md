# Scope — partial-recall

Last reconciled: 2026-06-24

`partial-recall` is the local-first search and memory engine for scholarly and
research corpora. It owns the generic engine layer: corpus adapter protocol,
text extraction, chunking, embeddings, SQLite storage, FTS/vector search, CLI,
and MCP tools. Domain repos own acquisition, source-specific parsing, and
domain interpretation.

This file is the canonical project scope. Older task files under `docs/` are
archived implementation inputs, not live scope authorities.

## Source Priority

1. `SCOPE.md` defines the current project boundary.
2. `ROADMAP.md` sequences versioned delivery.
3. `docs/ARCHITECTURE.md` defines the engine-vs-corpus contract.
4. `docs/*-scope.md` files preserve historical task specs only.

If these disagree, update this file and the roadmap together.

## Current Release Baseline

Current release: `v0.3.1`.

The text-corpus story is shipped:

- Zotero, Folder, Calibre, Markdown Notes, and JabRef adapters.
- PDF, TXT, MD, EPUB, and DOCX text extraction.
- Reading-order PDF extraction with a two-column regression test.
- Local ONNX, Gemini, and sentence-transformer embedding providers.
- SQLite vector store with FTS5 keyword search.
- CLI commands for init, doctor, index, status, search, fetch, place, serve,
  and keyring.
- MCP tools for semantic search, full-text search, status, item details,
  collections, library search, fetch, placement, and new-title discovery.

The old `place` scope is closed. The old `fetch` scope is no longer the live
scope document. It is now shipped. `fetch` resolves PDF, EPUB, and DOCX
attachments, and extracts reading-order text from each.

## Active Scope

### 1. Prove External Domain Adapters

Next engineering priority: prove the external `CorpusAdapter` seam from a
domain repo with a tiny CAD fixture.

Success means a domain repo can provide structured `Item` and `Source` records
while `partial-recall` handles chunking, embedding, indexing, search, and MCP.
Do not migrate Sansad, Budget, or CSR in bulk before this small adapter spike.

### 2. Verify Multilingual Retrieval

`v0.3.x` supports multilingual embedding models, but the repo has not yet
independently verified retrieval quality across South Asian and Arabic-Persian
scripts.

Current scope is verification, not claims expansion:

- Build small, cited fixtures for Tamil, Hindi, Bengali, Marathi, Urdu,
  Persian, and Arabic.
- Compare local ONNX, LaBSE, BGE-M3, and Gemini on real retrieval tasks.
- Record failure modes before changing model defaults.
- Keep public claims tied to verified results.

### 3. Prepare v0.5 OCR / HTR as a Pluggable Backend

OCR and handwriting/text-recognition belong in `partial-recall` only as a
generic, optional extraction backend. The engine may expose a protocol and
provenance model. It should not hardwire one heavy vision stack into the core
install.

The v0.5 planning target is:

- Tropy-compatible local manuscript image adapter.
- Optional OCR for printed text.
- Optional HTR / vision-LLM backend behind a small interface.
- Figure/plate handling through multimodal embeddings where useful.
- Provenance for every extracted page/block: backend, model, version,
  parameters, confidence where available, and source geometry where available.

Candidate backends to benchmark before adoption:

- Tesseract for baseline printed OCR.
- Kraken for historical and non-Latin scripts.
- Surya for layout-aware OCR, reading order, tables, and block geometry.
- Chandra for high-accuracy complex document conversion where the license and
  hardware constraints fit.

No Surya or Chandra dependency should enter the default install without a
benchmark against real CommonerLLP pages and a license review.

### 4. Fetch Gaps — CLOSED

`fetch` resolves Zotero PDF, EPUB, and DOCX attachments through one
`item_key -> attachment -> file` path. A PDF wins when an item carries more
than one, because annotations and page numbers only exist on the PDF.

Indexing covers the same three types. An EPUB-only or DOCX-only item is no
longer catalogue-only.

## Engine Responsibilities

`partial-recall` owns code that works across corpora:

- Corpus adapter protocol and registry.
- Generic file/text extraction.
- Generic OCR/HTR backend protocol, if added.
- Chunking and text hashing.
- Embedding provider interfaces and local/API providers.
- SQLite persistence, FTS, vector search, and future accelerators.
- CLI and MCP access to the shared engine.
- Retrieval provenance and reproducibility metadata.

## Out Of Scope

These are deliberately outside `partial-recall`:

- Domain crawling and source acquisition.
- CAD speaker segmentation, Sansad Q&A classification, budget forensics, or
  other domain-specific interpretation.
- A built-in chat or RAG synthesis layer.
- A GUI application.
- A hosted SaaS product, telemetry, or account system.
- Closed-source corpus systems such as Mendeley, EndNote, Paperpile,
  DEVONthink, Notion, or Roam.
- Heavy OCR/vision models as required default dependencies.

## Promotion Rule

A capability moves into `partial-recall` only if it is generic across corpora.
If it only makes sense for one source, it belongs in that source's domain repo.

For OCR/HTR specifically: add a protocol first, prove at least two backends can
fit it, and only then add adapters. The default install must remain usable on a
4-8 GB laptop.
