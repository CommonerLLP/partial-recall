# partial-recall

> *Semantic memory for your scholarly corpus. Because total recall was always a fiction.*

> **PRE-RELEASE — NOT FOR GENERAL USE.** partial-recall is under active development.
> It may lose data, corrupt indices, or behave in unexpected ways. Back up your research
> materials before indexing. No warranty is given. CommonerLLP and contributors accept no
> liability for any loss or damage arising from use. See [AGPL-3.0](./LICENSE).

**partial-recall is not about replacing humans doing their intellectual work.** It is an aid for when keyword and string-matching search are not useful — when you remember vaguely that you read something but not the exact words. It uses vector embeddings to bridge that gap, across multi-media formats (PDFs, notes, annotations, soon images and manuscript scans).

**Built for humanities and social-science scholars working with multilingual archives** — sources often not in their *modern* script (Persian, Arabic, Tamil, Bengali, pre-modern Devanagari, manuscript Latin, classical Chinese, and the long list of others), on laptops that may or may not have a GPU, and without budget for a SaaS subscription. The defaults assume no cloud account and no API key.

This is **a localized tool that scholars customise to fit their own corpora**. It is not a SaaS product, and not something that "just works out of the box." Indexing your corpus, choosing your embedding model, adapting to your languages and conventions — all of that is yours to configure. The tool stays out of your way; the reading is still yours to do.

## Status

**v0.3.0-dev — actively developed, not yet released.** Released minors so far:
v0.0.9, v0.1.0, v0.2.0–v0.2.4. See [ROADMAP.md](./ROADMAP.md) for the plan
to v0.3.0 and beyond.

**What is landing in v0.3.0:**
- **Five corpus adapters:** Zotero, folder-of-files, markdown notes folders
  (Obsidian, The Archive, Zettlr), JabRef/BibTeX, and Calibre e-book libraries.
- **EPUB and DOCX extraction** — no extra dependencies; stdlib zip+html/xml parsers.
- **Multilingual embedding via sentence-transformers** — LaBSE (109 languages,
  covers Tamil/Urdu/Bengali/Malayalam/Sinhala), BAAI/BGE-M3 (100+ languages,
  highest quality), and others. Automatic GPU/Metal acceleration on NVIDIA and
  Apple Silicon.
- **Hardware-aware init wizard** — detects your RAM and chip, asks what scripts
  your corpus covers, and recommends a calibrated model ladder with provenance,
  data-sovereignty notes, and documented military contracts for each option.
- FTS5 keyword search, auto-migration, Zotero library-richness in MCP responses,
  and OS-keyring secrets (all shipped in v0.2.x) remain stable.

### Where it's tested today

- **Primary dev machine:** Apple Silicon M1 (2020), 8 GB RAM, macOS.
- **CI matrix** (since v0.2.1): macOS-14, Ubuntu-22.04, Windows-2022
  × Python 3.11, 3.12. Every push to `main` and every PR runs the
  full test suite against all six cells.

### Where it's *designed* to run

The target audience is humanities and social-science scholars in
emerging markets — bahujan / Dalit, African, Indigenous-language,
working-class independent scholars — on the laptops they actually
own. That means the design target is:

- **4–8 GB RAM** is the baseline. 4 GB Intel i3/i5/i7, AMD Ryzen 3/5,
  and Apple Silicon all in scope. The default ONNX provider is
  CPU-only and the default model (`multilingual-e5-small` quantized
  to int8) is ~310 MB for a 15K-item corpus.
- **Linux / macOS first.** Unix is the design baseline.
- **Windows committed.** Many students are on Windows machines they
  did not choose; cross-platform CI lands Windows support as a
  first-class concern, not an afterthought.

### Where it's NOT designed to run

- **Chromebooks** — most are too RAM-constrained or locked-down to
  carry the ONNX model + a Python install. If you have a Chromebook
  with a Linux dev environment + 8 GB RAM you can try; this is not
  a supported path.
- **Phones / tablets** — not in scope. Mobile HTTP-client access to
  a self-hosted partial-recall is on the v0.x roadmap (the HTTP
  transport stub is sequenced for v0.2.4.1).

**GPU note:** CPU is the baseline floor — the tool never requires a GPU. If
you have an NVIDIA GPU (CUDA) or an Apple Silicon chip (Metal/MPS), the
`sentence-transformer` embedding provider detects and uses it automatically.
University Linux workstations and researchers with 16–24 GB Apple M-series
chips get hardware acceleration with zero configuration.

## Stance

What partial-recall **is**:

- **Retrieval, not synthesis.** No AI summarisation. No "ask the paper" chatbot wrapper. The tool surfaces passages; you read them.
- **Local-first.** No data leaves your laptop on the default configuration. Default embeddings run on your machine via ONNX.
- **AGPL-3.0 forever.** No paid tiers. No closed-source dependencies at runtime. Modify and self-host freely; release your modifications under the same terms.
- **Multilingual.** 100+ languages out of the box via `multilingual-e5-small` (ONNX). Hindi, Tamil, Bengali, Marathi, Urdu, Persian, Arabic, Mandarin, Spanish, and the rest.
- **Open-format interop only.** Works with Zotero, JabRef, Calibre, Obsidian (markdown files), and IIIF-served archives.

What it **is not**:

- Not a Mendeley / EndNote / Paperpile / DEVONthink / Notion plugin. These are closed formats; supporting them is not a roadmap item.
- Not a SaaS product. No cloud account. No telemetry, ever.
- Not GPU-required. CPU is the floor and the design target; GPU/Metal acceleration is a bonus when available.
- Not supported on Chromebooks. Most are too RAM-constrained or locked-down to run the ONNX model + a full Python install.

## Install

From PyPI (once published; not yet):

```bash
pipx install 'partial-recall[local,keyring]'
```

From source (the path today):

```bash
git clone https://github.com/CommonerLLP/partial-recall.git
cd partial-recall
pipx install '.[local,keyring]'
```

Or for development:

```bash
pip install -e ".[dev,local,keyring]"
```

### Extras

| extra | what it adds | required for |
|---|---|---|
| `local` | `onnxruntime`, `tokenizers`, `huggingface-hub` | default ONNX provider (`multilingual-e5-small`) |
| `multilingual` | `sentence-transformers` | LaBSE, BGE-M3, and other multilingual models with CUDA/Metal support |
| `gemini` | `httpx` | optional Gemini cloud API provider |
| `keyring` | `keyring` | OS-keyring secret storage (macOS Keychain / Linux Secret Service / Windows Credential Manager) |
| `faiss` | `faiss-cpu` | optional Faiss accelerator |
| `dev` | pytest, ruff, mypy, hypothesis, vcrpy | running the test suite + linting |
| `all` | local + multilingual + gemini + faiss + keyring | everything except `dev` |

For multilingual South Asian / Arabic / African corpora (Tamil, Urdu, Bengali, Malayalam, Swahili, etc.), install the multilingual extra and configure LaBSE or BGE-M3 via the init wizard:

```bash
pipx install 'partial-recall[local,multilingual,keyring]'
```

## First run

```bash
partial-recall init       # writes config.toml + asks four questions
partial-recall doctor     # runs 9 diagnostic checks against your install
partial-recall index      # builds the vector index
partial-recall search "your query"
```

For a step-by-step walkthrough that validates a fresh install
end-to-end, see [docs/walkthrough/five-minute-walkthrough.md](./docs/walkthrough/five-minute-walkthrough.md).
For known failure modes and their fixes, see
[docs/troubleshooting.md](./docs/troubleshooting.md). For every
config option in `config.toml`, see
[docs/config/reference.md](./docs/config/reference.md).

Tab-completion:

```bash
partial-recall --install-completion
```

A shorter `partial` alias is installed alongside.

## First run

### 1. Initialise

```bash
partial-recall init
```

The wizard walks through:

- **Corpus language survey** — asks what scripts your research materials are in
  (Latin-script only / South Asian scripts / Arabic-Persian / mixed). This drives
  the model recommendation.
- **Hardware detection** — silently reads your RAM and chip type, then shows a
  ranked ladder of embedding models calibrated to both. Each option shows:
  - RAM requirement, download size, language coverage
  - Who maintains the model and where they are headquartered
  - Open-weights or proprietary API
  - Documented defence/military contracts (factual, not opinion)
  - Whether your documents leave your machine or stay local
  - A plain-English disclaimer that these are suggestions, not guarantees — and
    that the risk is yours if you override the recommendation
- **Vector DB location** — defaults to a `platformdirs` user-data directory. If
  you supply an external-volume path, the wizard warns about portability risk.
- **Zotero auto-detection** — checks `~/Zotero/zotero.sqlite` and offers to wire
  it up.
- **MCP client snippet** — prints the JSON snippet to paste into your MCP client
  (Claude Code, Claude Desktop, etc.) if you want LLM-assisted search.

### 2. Build the index — two paths

**Path A: from scratch via local ONNX.** Takes roughly 3–5 hours for a 15,000-item Zotero library on an M1 MacBook. Re-embeds every chunk locally.

```bash
partial-recall index
```

**Path B: one-shot migration from the [`zotero-mcp` plugin](https://github.com/cookjohn/zotero-mcp).** `zotero-mcp` is an existing Zotero plugin (by GitHub user `cookjohn`) that builds a Gemini-embedded vector database alongside your library. If you already have one of those, import the existing vectors instead of recomputing. Roughly 10 minutes for the same 15,000 items, because the embeddings are copied, not re-generated.

```bash
partial-recall import cookjohn --source /path/to/zotero-mcp-vectors.sqlite
```

### 3. Sanity-check

```bash
partial-recall status
```

Reports corpus size, chunk count, vector count, embedding provider, and DB location.

### 4. Search from the CLI

```bash
partial-recall search "library policy India NPLIS"
```

Output looks like this (default human-readable):

```
                  partial-recall: top 5 for "NPLIS Chattopadhyaya 1986 national library policy"
┌─────┬─────────┬────────────┬────────────────────────────────────────────────────┬───────────────────────┬───────┬───────────────────────────────────────────────┐
│  #  │  Score  │  Date      │  Title                                             │  Authors              │  Src  │  Preview                                      │
├─────┼─────────┼────────────┼────────────────────────────────────────────────────┼───────────────────────┼───────┼───────────────────────────────────────────────┤
│  1  │ 0.758   │ 1996-05    │ Report of The Working Group of The Planning        │ Informatics, W.       │ pdf   │ Report of The Working Group of The Planning  │
│     │         │            │ Commission on Libraries and Informatics For The    │                       │       │ Commission on Libraries and Informatics For  │
│     │         │            │ Ninth Five Year Plan 1997-2002                     │                       │       │ The Ninth Five Year Plan 1997-2002           │
│  2  │ 0.733   │ 1994-01    │ Model Library Legislation Model Public Library Act │ Venkatappaiah, V.     │ pdf   │ Model Library Legislation Model Public…      │
│  3  │ 0.730   │ 2023       │ A Critical Study of Public Library Legislation of  │ Barman, M.; Lahkar, N.│ pdf   │ The credit of enacting a Library Act for     │
│     │         │            │ North East States of India                         │                       │       │ the first time in India goes to Kolhapur…    │
└─────┴─────────┴────────────┴────────────────────────────────────────────────────┴───────────────────────┴───────┴───────────────────────────────────────────────┘

Open in Zotero:
  [1] zotero://select/library/items/2UUZPVAX
  [2] zotero://select/library/items/RW6SZPLW
  [3] zotero://select/library/items/5HUHW4QU
```

The `zotero://...` URIs are clickable in most modern terminals (⌘-click on macOS, Ctrl-click on Linux/Windows): they open the item directly in your Zotero app.

For machine-readable output, pass `--json`:

```bash
partial-recall search "NPLIS Chattopadhyaya" --top-k 5 --json
```

Returns structured JSON suitable for piping into `jq`, downstream scripts, or your editor:

```json
{
  "query": "NPLIS Chattopadhyaya",
  "top_k": 5,
  "result_count": 5,
  "query_metadata": {
    "embedding_provider": "gemini",
    "embedding_model": "gemini-embedding-001",
    "active_run_id": 1,
    "vector_dim": 3072
  },
  "results": [
    {
      "rank": 1,
      "score": 0.758,
      "item_key": "2UUZPVAX",
      "corpus": "zotero",
      "zotero_uri": "zotero://select/library/items/2UUZPVAX",
      "item": {
        "type": "report",
        "title": "Report of The Working Group of The Planning Commission on Libraries and Informatics For The Ninth Five Year Plan 1997-2002",
        "date": "1996-05",
        "creators": [{"first": "Working Group", "last": "Informatics"}],
        "abstract": null
      },
      "source": {
        "type": "pdf",
        "ref": "cookjohn:0",
        "human_ref": "pdf",
        "preview": "Report of The Working Group of The Planning Commission..."
      },
      "chunk": {
        "id": 1,
        "index": 0,
        "char_offset_start": null,
        "char_offset_end": null,
        "detected_locale": null
      }
    }
  ]
}
```

### 5. Optional: MCP server

**You don't need this step.** partial-recall is a standalone CLI — Section 4 above is the primary surface. The terminal search command works on its own.

This step is only for users who want an LLM client to call partial-recall as a tool during a conversation. partial-recall implements the [Model Context Protocol](https://modelcontextprotocol.io) and works with any MCP-compatible client. To run the server over stdio:

```bash
partial-recall serve
```

Or let your client spawn it automatically — the `init` wizard prints the JSON snippet you paste into your client's settings.

## Roadmap

See [ROADMAP.md](./ROADMAP.md) for the full plan.

**What's coming after v0.3.0:**
- IIIF image manifests (British Library, Bodleian, BnF, Vatican) for manuscript corpora
- Local manuscript-image OCR (low-resource Indic script models)
- Better multilingual chunking (tokenizer-aware splitting for Tamil, Bengali, Urdu)
- i18n: Hindi, Tamil, Bengali, Urdu, Swahili interface strings (gettext scaffolding)

## License

[AGPL-3.0-or-later](./LICENSE). If you modify and run this as a network-accessible service, you must release your modifications under the same license. This preserves the commons.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).
