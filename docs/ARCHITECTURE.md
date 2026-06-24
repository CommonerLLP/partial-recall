# Architecture — partial-recall

> **Who must read this:** every developer or agent working in any
> CommonerLLP repo that touches corpora, search, crawling, or MCP
> serving. Not optional. Read before scoping any new feature.
>
> **Last updated: 2026-06-24**

---

## The one-sentence design

`partial-recall` is the search and memory engine for the CommonerLLP org.
Every corpus — parliamentary debates, budget documents, Zotero library,
academic papers — is an instance of one protocol. The engine is shared.
The domain intelligence lives in the corpus.

---

## Engine vs corpus: the fundamental split

```
partial-recall (engine)          domain repos (corpus producers)
─────────────────────────────    ──────────────────────────────────
CorpusAdapter protocol           implement CorpusAdapter
PDF/text extraction              know how to acquire their source
chunking                         know their document structure
embedding (local + API)          know their domain schema
SQLite vector store              register with the engine
FTS5 keyword index               add domain-specific tools on top
MCP server + 9 tools             that is all
```

The engine does not know what a Finance Commission is.
The corpus adapter does not know what an embedding is.
That boundary is the architecture.

**The test for any new code:** if it would work identically for any
corpus, it belongs in `partial-recall`. If it only makes sense for one
specific source (CAD speaker segmentation, OBI budget forensics, Lok
Sabha Q&A classification), it belongs in the domain repo.

---

## The CorpusAdapter protocol (the contract)

Source: `src/partial_recall/corpus/protocol.py`

```python
class CorpusAdapter(Protocol):

    @property
    def name(self) -> str: ...           # corpus identifier, e.g. "cad", "sansad"

    @property
    def version(self) -> str: ...        # adapter version for cache invalidation

    @property
    def capabilities(self) -> set[ItemKind]: ...  # TEXT, NOTE, IMAGE, etc.

    def list_items(self, since: datetime | None = None) -> Iterator[Item]: ...
    def count_items(self, since: datetime | None = None) -> int | None: ...
    def get_sources(self, item: Item) -> Iterator[Source]: ...
    def get_text(self, item: Item, source: Source) -> str | None: ...
    def get_image(self, item: Item, source: Source) -> bytes | None: ...
    def close(self) -> None: ...
```

Implement these eight methods. Register the adapter. You get for free:

- chunking (recursive char, 1024 / 128 overlap)
- embedding (multilingual-e5-small local; Gemini opt-in)
- deduplication (text_hash)
- SQLite vector store (7 tables, WAL mode)
- FTS5 full-text index
- MCP tools: `semantic_search`, `search_fulltext`, `semantic_status`,
  `get_item_details`, `list_collections`, `library_search`, `place_item`,
  `fetch_item`, `whats_new`
- CLI: `partial-recall index`, `partial-recall search`

You write ~200 lines. You get a production search stack.

---

## Existing adapters

| Adapter | Corpus | Status | Lives in |
|---|---|---|---|
| `ZoteroAdapter` | Zotero library (PDFs + abstracts) | Shipped v0.0.1 | `partial-recall` |
| `FolderAdapter` | Any directory of PDFs/text/epub/docx | Shipped v0.1.0 | `partial-recall` |
| `JabRefAdapter` | JabRef bibliography | In progress | `partial-recall` |
| `CalibreAdapter` | Calibre library | In progress | `partial-recall` |
| `MarkdownNotesAdapter` | Markdown note directories | In progress | `partial-recall` |
| `CADAdapter` | Constituent Assembly Debates | **Planned** | `cad-mcp` |
| `SansadAdapter` | Lok Sabha Q&A | **Planned** | `sansad-semantic-crawler` |
| `BudgetAdapter` | OBI / state budget documents | **Planned** | `budget-crawler` |

---

## What a new domain repo looks like

A domain repo has exactly three jobs:

**1. Acquire** — crawl, download, probe, scrape the source.
Domain-specific. No shared code exists for this; each source is different.

**2. Structure** — parse, segment, normalise into `Item` + `Source` objects
the adapter protocol understands. Domain intelligence lives here:
speaker segmentation for CAD, Q&A classification for sansad,
forensic audit logic for budgets.

**3. Register** — implement `CorpusAdapter`, point `partial-recall` at it.
From that point on, search is the engine's problem, not the domain repo's.

**What a domain repo must not do:**
- Build its own chunker
- Build its own embedding pipeline
- Build its own FTS5 index
- Build its own MCP server
- Build its own vector store

If you find yourself doing any of those, you are building a second
`partial-recall`. Stop. Open an issue in `partial-recall` instead and
discuss whether the engine needs extending.

---

## The FolderAdapter shortcut

If the corpus is a directory of PDFs with no special structure,
you do not need to write a corpus adapter at all:

```bash
partial-recall index --corpus-type folder --path /path/to/pdfs --name my-corpus
```

The FolderAdapter handles extraction, chunking, embedding, and indexing.
Use this for any corpus where the documents are the unit of retrieval
and you do not need per-document metadata beyond filename + path.

For corpora with rich internal structure (CAD sessions have dates,
speakers, article references; sansad Q&A has questioner, ministry,
session number) — write a proper adapter that preserves that structure
as Item metadata.

---

## The org topology

```
Layer 0  sansad-semantic-crawler   shared crawl library, parliament sources
         ↓ pip install (pinned)
Layer 1  partial-recall            engine: chunk, embed, index, search, serve
         ↓ CorpusAdapter instances
Layer 2  cad-mcp                   CAD corpus + session/context tools
         sansad (as corpus)        parliament Q&A corpus
         budget-crawler            OBI/budget corpus + forensic tools
         ↓ search results
Layer 3  theright2read             public dashboard
         academiaindia             public dashboard
```

Full topology with capability registry: `_org/architecture.md`.

---

## History (for orientation, not re-litigation)

`sansad-semantic-crawler` was built first and discovered the need for
corpus search through practice. `partial-recall` was extracted from that
experience as the correct shared solution — a deliberate DRY move.

In May 2026, `cad-mcp` was built with a full duplicate search stack
(FTS5, MCP server, search tools) in a single session, because this
architectural contract did not exist as a written document. This file
exists because of that session.

The extraction from sansad to partial-recall was the right move.
Repeating that extraction in every new domain repo is the wrong move.

---

## Data flow and method calls across repos

```
╔══════════════════════════════════════════════════════════════════════╗
║  ACQUISITION LAYER                                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  cad-mcp/ingest/download.py                                          ║
║  ├── http_get(url)              urllib.request + retry/backoff       ║
║  ├── probe(handle)              GET eparlib.sansad.in/handle/…       ║
║  │   └── regex → bitstream URL                                       ║
║  └── fetch(url, dest)          → data/pdfs/cad_DD-MM-YYYY.pdf        ║
║                                                                      ║
║  cad-mcp/ingest/parse.py                                             ║
║  ├── pdf_to_text(path)          subprocess pdftotext                 ║
║  ├── SPEAKER_RE.finditer(text)  → (speaker, body) pairs             ║
║  └── sqlite3.connect(cad.db)   → sessions + speeches tables         ║
║                                                                      ║
║  sansad-semantic-crawler                                             ║
║  ├── http_client.StdlibSession  urllib, no cache                     ║
║  ├── crawl()                    GET sansad.in/…                      ║
║  ├── parse_qa()                 → Question, Answer objects           ║
║  └── classify(topic_profile)    regex|embedding|llm|ensemble        ║
║                                                                      ║
║  budget-crawler/budget_crawler/                                      ║
║  ├── scrapping_utils.ScrappingUtils   requests + HTTPAdapter retry   ║
║  ├── obi_utils.OBIUtils               (duplicate of above — debt)    ║
║  ├── rbi_fetcher.fetch()              GET RBI state finance PDFs     ║
║  ├── pdf_extractor.extract()          pdfplumber → text              ║
║  └── sqlite3 ad-hoc writes    → db/*.db                             ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  ENGINE LAYER  ←  partial-recall                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  corpus/protocol.py                                                  ║
║  └── CorpusAdapter (Protocol)                                        ║
║      ├── .list_items()     → Iterator[Item]                          ║
║      ├── .get_sources()    → Iterator[Source]                        ║
║      └── .get_text()       → str | None                              ║
║                                                                      ║
║  corpus/adapters/                                                    ║
║  ├── ZoteroAdapter.list_items()   reads ~/Zotero/zotero.sqlite (RO) ║
║  ├── FolderAdapter.list_items()   walks directory, reads files       ║
║  ├── [CADAdapter]                 PLANNED — lives in cad-mcp         ║
║  └── [SansadAdapter]              PLANNED — lives in sansad-crawler  ║
║                                                                      ║
║  extract/pdf.py                                                      ║
║  └── extract_pdf_text(path)       pypdf + pdfplumber                 ║
║                                                                      ║
║  chunk/                                                              ║
║  └── RecursiveCharChunker         1024 chars / 128 overlap           ║
║      └── .chunk(text)             → list[Chunk]                      ║
║                                                                      ║
║  embedding/                                                          ║
║  ├── LocalONNXProvider            multilingual-e5-small, CPU         ║
║  │   └── .embed(texts)            → list[np.ndarray]                 ║
║  └── GeminiProvider (opt-in)      gemini-embedding-001, API          ║
║      └── .embed(texts)            → list[np.ndarray]                 ║
║                                                                      ║
║  store/                                                              ║
║  └── VectorStore (SQLite, WAL)    7 tables                           ║
║      ├── .upsert_item(item)       idempotent, text_hash dedup        ║
║      ├── .upsert_chunk(chunk)     stores text + vector (int8)        ║
║      └── .search_fulltext(q)      FTS5 → ranked hits                 ║
║                                                                      ║
║  index/                                                              ║
║  └── IndexPipeline.run()                                             ║
║      adapter.list_items()                                            ║
║        → get_sources() → get_text()                                  ║
║          → extract_pdf_text()                                        ║
║            → RecursiveCharChunker.chunk()                            ║
║              → embedding.embed()                                     ║
║                → VectorStore.upsert_chunk()                          ║
║                                                                      ║
║  mcp/server.py   (stdio JSON-RPC 2.0)                                ║
║  ├── semantic_search(query)       embed → cosine → top-k hits        ║
║  ├── search_fulltext(query)       FTS5 → ranked hits                 ║
║  ├── semantic_status()            → index stats                      ║
║  ├── get_item_details(item_key)   → full item metadata               ║
║  ├── list_collections()           → corpus collections               ║
║  ├── library_search(query)        → Zotero SQLite title/creator hits ║
║  ├── place_item(item_key)         → corpus positioning               ║
║  ├── fetch_item(item_key)         → attachment fetch/text extraction ║
║  └── whats_new()                  → discovery/new-title candidates   ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  DOMAIN TOOL LAYER  ←  thin wrappers on top of engine MCP           ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  cad-mcp/server/mcp_server.py  (current — contains debt)            ║
║  ├── cad_search()    ← DEBT: duplicates search_fulltext              ║
║  ├── cad_stats()     ← DEBT: duplicates semantic_status              ║
║  ├── cad_session(date)          reads sessions table  ← KEEP        ║
║  └── cad_context(speech_id)     reads speeches table  ← KEEP        ║
║                                                                      ║
║  target state (post-remediation):                                    ║
║  cad-mcp exposes only cad_session + cad_context                     ║
║  search goes through partial-recall MCP tools directly              ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  SURFACE LAYER                                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  theright2read                                                       ║
║  └── sansad-semantic-crawler (pip, pinned v0.2.0)                   ║
║      → corpus-refresh → assets/parliament_libraries.js               ║
║      → static GH Pages site                                          ║
║                                                                      ║
║  academiaindia                                                        ║
║  └── sansad-semantic-crawler (pip, pinned v0.2.0)                   ║
║      → make scrape → docs/data/*.json                                ║
║      → static GH Pages site + Vitest frontend tests                 ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝

DEBT ITEMS (annotated inline above with ← DEBT):
  1. cad-mcp search tools duplicate partial-recall  [HIGH]
  2. budget-crawler scrapping_utils ≈ obi_utils     [MEDIUM]
  3. budget-crawler/zotero_semantic_search.py       [fossil — delete]
  4. budget-crawler/sansad_vacancy_scraper.py       [delete, import sansad]
```
