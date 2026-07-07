# Five-minute walkthrough

A new install validated end-to-end. You'll go from `pipx install`
to indexing a small corpus to running a semantic search, in
roughly five minutes on an Apple Silicon M1 with 8 GB RAM. Times
will be longer on slower CPUs; the steps are the same.

What this walkthrough proves works in v0.3.0:

- `pipx install` succeeds
- `partial-recall init` writes a config you can read
- `partial-recall doctor` reports the install state honestly
- A Folder corpus can be indexed (no Zotero required)
- `partial-recall search` returns ranked results
- The MCP server (`partial-recall serve`) launches over stdio
- The keyring stores a fake API key (no real Gemini call made)

Other corpus sources available but not covered here: Calibre (`--source calibre`),
Markdown notes (`--source markdown_notes`), JabRef (`--source jabref`),
Zotero (`--source zotero`).

---

## 1. Install (≈ 60s)

```zsh
# Recommended: pipx (isolates partial-recall in its own venv)
pipx install 'partial-recall[local,keyring]'

# OR for a fresh checkout in development:
# git clone https://github.com/CommonerLLP/partial-recall.git
# cd partial-recall
# pip install -e ".[dev,local,keyring]"
```

Check:

```zsh
partial-recall --version
# → partial-recall 0.3.1
```

If you get `command not found: partial-recall`, see
[troubleshooting → PATH](#path).

## 2. First-run init (≈ 30s)

```zsh
partial-recall init
```

The wizard now adapts to your hardware and corpus languages:

1. **Corpus language.** Pick `1` (Latin-script) for a first run in
   English. Change to `2` (South Asian scripts) if your corpus is in
   Tamil, Urdu, Bengali, Malayalam, or Hindi.
2. **Embedding model.** The wizard detects your RAM and shows a ranked
   list. Pick `1` (the recommended model) for the first run. Each
   option shows who maintains it, whether it's open-source, and any
   documented military contracts.
3. **Vector DB path.** Accept the default (under your platform's
   user data dir, e.g. `~/.local/share/partial-recall/` on Linux).
4. **Default Zotero?** Say `n` for now; we're going to use a
   small folder corpus instead.
5. **Skip Zotero?** Say `y`.

Then under `[folder]` in the written config, edit it to enable
the folder corpus and point at a sample directory:

```toml
[folder]
enabled = true
paths = ["/path/to/a/small/folder/of/text/and/pdfs"]
recursive = true
extensions = [".pdf", ".txt", ".md"]
```

## 3. Doctor smoke (≈ 5s)

```zsh
partial-recall doctor
```

Expected lines:
- `python_version: ok`
- `config_present: ok`
- `embedding_provider: ok (local-onnx, deps importable)`
- `vector_store: warn — no indexing has run yet` ← expected before
  first `index`
- `zotero_source: skip` ← because you set `enabled = false`
- `folder_source: ok`
- `pth_uf_hidden: ok` (macOS only)
- `disk_space: ok`

Any `fail` row's hint tells you what to fix.

## 4. Index the folder (≈ 60–120s on first run; ONNX downloads ~470 MB)

```zsh
partial-recall index --source folder
```

You'll see:

- a one-time ONNX model download (~470 MB; cached for future runs)
- a determinate progress bar with the current item title
- a plain-English note about pypdf warnings (they're recovery
  messages, not errors)
- a final summary: `Indexed N items, M chunks, V new vectors
  (run_id=1)`

## 5. Search (≈ 1s)

```zsh
partial-recall search "your query here" --limit 5
```

A Rich table with rank / score / date / title / authors /
source / preview. Below the table, clickable `zotero://` links
for any Zotero items in the results (none, in this folder-only
walkthrough).

## 6. Full-text (keyword) search (≈ 1s)

```zsh
# search_fulltext is a v0.2.4 MCP tool, not yet a CLI command;
# use the MCP server for it. See the next step.
```

## 6. Fetching and Placing Items (≈ 5s)

```zsh
# Once you find an item via search, you can fetch its raw text (e.g., from Zotero PDF)
partial-recall fetch <item_key> --text

# Or place a candidate title against the existing corpus to see if you already have it
partial-recall place --title "The Annihilation of Caste"
```

## 7. MCP server smoke (≈ 5s)

```zsh
# In one terminal:
partial-recall serve
# (silently waits on stdio for MCP requests)

# In another shell, OR wire into Claude Code:
claude mcp add partial-recall ~/.local/bin/partial-recall -- serve
```

Then any MCP client (Claude Code, Continue, etc.) sees nine tools:

- `semantic_search` — vector search
- `search_fulltext` — FTS5 keyword/phrase search
- `semantic_status` — index totals + active embedding-run metadata
- `get_item_details` — full item metadata + library-location + collections
- `list_collections` — Zotero collections with item-count per
- `library_search` — structured metadata search (author, tag, year)
- `fetch_item` — retrieves clean reading-order text for an item
- `place_item` — semantic duplicate check against your corpus
- `whats_new` — chronological discovery of newly released works

## 8. Keyring (optional; only if you'll use Gemini later)

```zsh
partial-recall keyring set-gemini
# Prompts you (hidden input) for your Gemini API key; stores it
# in macOS Keychain / Linux Secret Service / Windows Credential
# Manager via the `keyring` package.

partial-recall keyring status
# Shows masked prefix + backend name to confirm the entry exists.
```

After this, switch your `[embedding] provider = "gemini"` in
config and `partial-recall search` will resolve the key from the
keyring automatically. No env vars needed.

---

## What you've just verified

- The Python install path is intact (`pipx` resolved on your PATH)
- The platform's user data dir is writable (`init` wrote a config)
- The ONNX model loads and produces vectors on your CPU
- The chunker handles your folder's actual files
- SQLite WAL mode is working (the vector DB committed)
- The MCP server starts (stdio handshake succeeds)
- OS keyring is configured (Keychain / Secret Service / Credential
  Manager)

If all eight worked end-to-end, partial-recall is correctly
installed on your machine. If one didn't, the
[troubleshooting](../troubleshooting.md) doc walks through what
each failure looks like and how to fix it.

---

## What this walkthrough does NOT cover (intentionally)

- Real Gemini API calls (would require your key + cost money)
- Indexing a 30K-item Zotero library (covered separately in the
  `zotero-corpus.md` how-to)
- Re-embedding (top-up) with `--extend` (covered in the indexing
  how-to)
- Cross-platform packaging / distribution
- Building a docs site (just plain Markdown files for now)
