# partial-recall

> *Semantic memory for your scholarly corpus. Because total recall was always a fiction.*

**partial-recall is not about replacing humans doing their intellectual work.** It is an aid for when keyword and string-matching search are not useful — when you remember vaguely that you read something but not the exact words. It uses vector embeddings to bridge that gap, across multi-media formats (PDFs, notes, annotations, soon images and manuscript scans).

**Built for humanities and social-science scholars working with multilingual archives** — sources often not in their *modern* script (Persian, Arabic, Tamil, Bengali, pre-modern Devanagari, manuscript Latin, classical Chinese, and the long list of others), on laptops without a GPU, and without budget for a SaaS subscription. The defaults assume none of those luxuries: CPU-only, no cloud account, no API key.

This is **a localized tool that scholars customise to fit their own corpora**. It is not a SaaS product, and not something that "just works out of the box." Indexing your corpus, choosing your embedding model, adapting to your languages and conventions — all of that is yours to configure. The tool stays out of your way; the reading is still yours to do.

## Status

**v0.0.1 — first proof-of-life release.** Tested so far on Apple Silicon Mac (macOS, 16 GB RAM). Lower-spec hardware should work — the default ONNX provider is CPU-only — but has not yet been verified. Linux and Windows are v0.1.0 work. See [ROADMAP.md](./ROADMAP.md).

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
- Not cross-platform yet. v0.0.1 is macOS-tested. Linux + Windows ship with v0.1.0.

## Install

From PyPI (once published):

```bash
pipx install partial-recall
```

From source (the path for v0.0.1 right now):

```bash
git clone https://github.com/CommonerLLP/partial-recall.git
cd partial-recall
pipx install .
```

Or for development:

```bash
pip install -e ".[dev,local]"
```

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

- **Embedding provider** — choose from curated profiles, not raw model SKUs:
  1. English-only (faster, smaller)
  2. Multilingual (default; `multilingual-e5-small` ONNX, 100+ languages)
  3. Gemini cloud — *your choice*. Using a cloud provider sends your chunks to Google's servers for embedding, and Google bills you for the API calls. The tool supports it (e.g. for 3072-dim quality, or for `zotero-mcp`-imported corpora that are already Gemini-embedded), but it is never the default. Pick option 2 if you want everything to stay on your laptop.
  4. Advanced (specify your own model)
- **Vector DB location** — defaults to a `platformdirs` user-data directory. If you supply an external-volume path, the wizard warns about portability and unmount risk.
- **Zotero auto-detection** — checks `~/Zotero/zotero.sqlite` and offers to wire it up.
- **MCP client snippet (optional)** — if you want to use partial-recall from an LLM client that speaks the Model Context Protocol, the wizard prints the JSON snippet to paste into that client's settings. Skip if you only want the terminal CLI.

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

See [ROADMAP.md](./ROADMAP.md) for what's coming:

- **v0.1.0** — Folder-of-PDFs adapter, HTTP transport, cross-platform CI (Linux + Windows), keyring-backed secrets, skip-already-indexed flag, bibliography output mode.
- **v0.2.0 and beyond** — Obsidian vaults, IIIF (British Library, Bodleian, BnF, Vatican, Stanford, Princeton), Indic-strong embedding models, local manuscript-image OCR.

## License

[AGPL-3.0-or-later](./LICENSE). If you modify and run this as a network-accessible service, you must release your modifications under the same license. This preserves the commons.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).
