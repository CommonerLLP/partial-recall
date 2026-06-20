# partial-recall

> *Semantic memory for your scholarly corpus. Because total recall was always a fiction.*

**partial-recall is not about replacing humans doing their intellectual work.** It is an aid for when keyword and string-matching search fail — when you remember vaguely that you read something but not the exact words. It uses vector embeddings to bridge that gap across PDFs, notes, annotations, EPUBs, and DOCX files.

**Built for humanities and social-science scholars working with multilingual archives** — sources often not in their modern script, on laptops that may or may not have a GPU, and without budget for a SaaS subscription. The defaults assume no cloud account and no API key.

This is a tool scholars customise to fit their own corpora. Indexing your corpus, choosing your embedding model, adapting to your languages and conventions — all of that is yours to configure. The tool stays out of your way; the reading is still yours to do.

> **PRE-RELEASE — NOT FOR GENERAL USE.** partial-recall is under active development.
> It may lose data, corrupt indices, or behave in unexpected ways. Back up your research
> materials before indexing. No warranty is given. CommonerLLP and contributors accept no
> liability for any loss or damage arising from use. See [AGPL-3.0](./LICENSE).

---

## Install

```bash
pipx install 'partial-recall[local,keyring]'
```

For larger multilingual models (LaBSE, BGE-M3, multilingual-e5-large):

```bash
pipx install 'partial-recall[local,multilingual,keyring]'
```

A shorter `partial` alias is installed alongside `partial-recall`.

---

## First run

```bash
partial-recall init       # hardware-aware wizard; writes config.toml
partial-recall doctor     # diagnostic checks against your install
partial-recall index      # builds the vector index from your corpus
partial-recall search "your query"
partial-recall fetch <item_key>  # fetch clean reading-order text from an item's attachment
partial-recall place "title"     # place a candidate work against the existing corpus
```

For a step-by-step walkthrough see [docs/walkthrough/five-minute-walkthrough.md](./docs/walkthrough/five-minute-walkthrough.md).
For known failure modes see [docs/troubleshooting.md](./docs/troubleshooting.md).
For every config option see [docs/config/reference.md](./docs/config/reference.md).

Tab-completion:

```bash
partial-recall --install-completion
```

---

## What the init wizard does

`partial-recall init` walks through:

- **Corpus language survey** — asks what scripts your research materials are in (Latin-script / South Asian scripts / Arabic-Persian / mixed). Drives the model recommendation.
- **Hardware detection** — reads your RAM and chip type silently, then shows a ranked ladder of embedding models calibrated to both. Each option shows: RAM requirement, download size, language coverage, maintainer and their HQ country, open-weights or proprietary API, and documented defence/military contracts (factual, not opinion).
- **Vector DB location** — defaults to a `platformdirs` user-data directory. External-volume paths are accepted with a portability warning.
- **Zotero auto-detection** — checks `~/Zotero/zotero.sqlite` and offers to wire it up.
- **MCP client snippet** — prints the JSON to paste into your MCP client (Claude Code, Claude Desktop) if you want LLM-assisted search.

---

## Corpus sources

| Adapter | What it indexes |
|---|---|
| **Zotero** | PDFs, abstracts, notes, annotations, collection memberships |
| **Folder** | Recursive walk of PDFs, TXT, MD, EPUB, DOCX |
| **Calibre** | E-book library via `metadata.db`; no Calibre install required |
| **Markdown notes** | Obsidian, The Archive, Zettlr vaults; YAML frontmatter; `.partial-recallignore` |
| **JabRef** | BibTeX `.bib` files; abstracts + linked PDFs |
| **External** | Load custom adapters via dotted import path (e.g. `package.module:AdapterClass`) |

---

## Embedding models

| Model | Provider | RAM | Languages | Notes |
|---|---|---|---|---|
| `multilingual-e5-small` | `local-onnx` | ~1 GB | 50 (Latin-strong) | Default. No extras needed. Works on 4 GB RAM. |
| `multilingual-e5-large` | `sentence-transformer` | ~2 GB | 50 (Latin-strong) | Better quality for European academic prose. |
| `LaBSE` | `sentence-transformer` | ~2.5 GB | 109 | Designed for South Asian + Arabic scripts. See note below. |
| `BGE-M3` | `sentence-transformer` | ~3.5 GB | 100+ | Highest local quality. See note below. |
| `gemini-embedding-001` | `gemini` | — | Multilingual | Cloud API. Data leaves your machine. |

**Note on multilingual coverage:** LaBSE and BGE-M3 are designed for Tamil, Hindi, Bengali, Urdu, Persian, and Arabic per their respective model documentation. Retrieval quality across these scripts has not yet been independently verified by partial-recall. Independent verification is planned for v0.4.0.

GPU/Metal acceleration is used automatically when available (NVIDIA CUDA, Apple Silicon MPS). CPU is the baseline — the tool never requires a GPU.

---

## Search

```bash
partial-recall search "library policy India NPLIS"
```

Output:

```
                  partial-recall: top 5 for "NPLIS Chattopadhyaya 1986 national library policy"
┌─────┬─────────┬────────────┬────────────────────────────────────────────────────┬───────────────────────┬───────┬───────────────────────────────────────────────┐
│  #  │  Score  │  Date      │  Title                                             │  Authors              │  Src  │  Preview                                      │
├─────┼─────────┼────────────┼────────────────────────────────────────────────────┼───────────────────────┼───────┼───────────────────────────────────────────────┤
│  1  │ 0.758   │ 1996-05    │ Report of The Working Group of The Planning        │ Informatics, W.       │ pdf   │ Report of The Working Group of The Planning  │
│  2  │ 0.733   │ 1994-01    │ Model Library Legislation Model Public Library Act │ Venkatappaiah, V.     │ pdf   │ Model Library Legislation Model Public…      │
│  3  │ 0.730   │ 2023       │ A Critical Study of Public Library Legislation     │ Barman, M.; Lahkar, N.│ pdf   │ The credit of enacting a Library Act…        │
└─────┴─────────┴────────────┴────────────────────────────────────────────────────┴───────────────────────┴───────┴───────────────────────────────────────────────┘

Open in Zotero:
  [1] zotero://select/library/items/2UUZPVAX
  [2] zotero://select/library/items/RW6SZPLW
  [3] zotero://select/library/items/5HUHW4QU
```

The `zotero://...` URIs open the item directly in your Zotero app (⌘-click on macOS, Ctrl-click on Linux/Windows).

For machine-readable output:

```bash
partial-recall search "NPLIS Chattopadhyaya" --top-k 5 --json
```

---

## MCP server (optional)

You don't need this. partial-recall is a standalone CLI — the `search` command above is the primary surface.

This step is only for users who want an LLM client (Claude Code, Claude Desktop) to call partial-recall as a tool during a conversation.

```bash
partial-recall serve
```

Or let your client spawn it automatically — `partial-recall init` prints the JSON snippet to paste into your client's settings.

Available MCP tools: `semantic_search`, `search_fulltext`, `semantic_status`, `get_item_details`, `list_collections`, `library_search`, `fetch_item`, `place_item`, `whats_new`.

---

## Hardware requirements

Design target: **4–8 GB RAM**. Intel i3/i5/i7, AMD Ryzen 3/5, and Apple Silicon all in scope.

| Platform | Support |
|---|---|
| macOS (Apple Silicon) | Primary dev machine. Full support. |
| macOS (Intel) | Supported. No Metal acceleration. |
| Linux (x86-64) | Full support. CUDA acceleration if GPU present. |
| Windows (x86-64) | CI-green since v0.2.1. Supported. |
| Chromebooks | Not supported. Most are too RAM-constrained. |
| Phones / tablets | Not in scope. |

---

## What it is and is not

**Is:**
- **Retrieval, not synthesis.** No AI summarisation. No "ask the paper" chatbot. The tool surfaces passages; you read them.
- **Local-first.** No data leaves your laptop on the default configuration. Default embeddings run on your machine via ONNX.
- **AGPL-3.0 forever.** No paid tiers. No closed-source dependencies at runtime. Modify and self-host freely; release your modifications under the same terms.
- **Open-format interop only.** Works with Zotero, JabRef, Calibre, Obsidian, and plain markdown.

**Is not:**
- Not a Mendeley / EndNote / Paperpile / DEVONthink / Notion plugin. Closed formats are not on the roadmap.
- Not a SaaS product. No cloud account. No telemetry, ever.
- Not GPU-required. CPU is the floor; GPU/Metal is a bonus.
- Not a replacement for Zotero. It reads Zotero's data; it does not replace Zotero's authoring and citation features.

---

## For developers and contributors

### Dev install

```bash
git clone https://github.com/CommonerLLP/partial-recall.git
cd partial-recall
pip install -e ".[dev,local,keyring]"
pytest -q -m "not slow and not live"
```

### Extras

| extra | what it adds |
|---|---|
| `local` | `onnxruntime`, `tokenizers`, `huggingface-hub` — default ONNX provider |
| `multilingual` | `sentence-transformers` — LaBSE, BGE-M3, and other HuggingFace models |
| `gemini` | `httpx` — Gemini cloud API provider |
| `keyring` | `keyring` — OS-keyring secret storage |
| `faiss` | `faiss-cpu` — optional Faiss accelerator |
| `dev` | pytest, ruff, mypy, hypothesis, vcrpy |
| `all` | local + multilingual + gemini + faiss + keyring |

### CI matrix

macOS-14, Ubuntu-22.04, Windows-2022 × Python 3.11, 3.12. Every push to `main` and every PR runs the full test suite against all six cells.

### Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## Roadmap and status

**Current release: v0.3.0.**

See [ROADMAP.md](./ROADMAP.md) for the full plan.

**What's next:**
- Faiss accelerator for faster semantic search on large corpora
- Independent verification of multilingual retrieval quality across Tamil, Hindi, Bengali, Urdu, Persian, Arabic
- Better chunking for non-Latin scripts

---

## License

[AGPL-3.0-or-later](./LICENSE). If you modify and run this as a network-accessible service, you must release your modifications under the same license. This preserves the commons.
