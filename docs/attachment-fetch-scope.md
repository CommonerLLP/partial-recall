# Scope of work — attachment fetch / clean-text retrieval

> Authored 2026-06-19 from a **governingclaste** session (sister consumer). Drop-in
> spec for the next partial-recall agent. Read `docs/ARCHITECTURE.md` first; claim
> scope in `WORKING.md` before editing code. governingclaste explicitly declined to
> build its own `zotero_pull.py` (DRY — the corpus/Zotero layer is yours, not a
> consumer's) and handed the capability here.

## One-line goal

Given an `item_key` from a search hit, return the **actual source file** (PDF/EPUB)
and/or its **clean, reading-order text** — so a consumer can read the real passage
instead of the scrambled multi-column preview that `semantic_search` returns today.

## Why (the consuming workflow)

A consumer (governingclaste, twenty27, any corpus reader) runs `semantic_search`,
gets a hit, and wants to **quote the source verbatim**. Two failure modes hit us
this session:

1. **Scrambled previews.** EPW (and most two-column journal PDFs) get extracted
   *across* columns, so the chunk text interleaves column A and column B word-by-word.
   Example hit — Teltumbde, "Saffron Neo-liberalism" (EPW 2014, item `28H8BQST`) —
   came back as `"...merely to appoint Nripendra Misra as his trade and investment
   for the benefit of big not needed. Modi therefore would not principal secretary,
   the fascist streak in business..."`. Unreadable; the real sentence is two columns
   stitched wrong.
2. **item_key → file resolution is non-obvious.** The file *was* on disk, but under
   the **attachment** key (`~/Zotero/storage/NTWRI8PI/`), not the parent item key
   (`storage/28H8BQST/`). A naive `storage/<item_key>/` lookup — what a consumer
   reaches for — finds nothing and wrongly concludes the file is missing (we did
   exactly this). You must resolve **parent → attachment-child key** first (local
   `zotero.sqlite`, or the Web API `children` call), *then* hit the filesystem; and
   fall back to the Web API `/file` blob only when the attachment is genuinely remote
   (`imported_url` not yet synced, or a library you don't hold locally).

Today there is **no partial-recall affordance** for either: a consumer must manually
do the parent→child resolution and either locate the storage path or curl the Web
API — exactly the undifferentiated lifting this repo is supposed to own. (Local-first
is also cheaper: prefer `storage_path` when present, network only as fallback.)

## Proven mechanics (do NOT re-derive — we already verified these)

- Item → attachment: the PDF is a **child item** of the parent, `itemType:
  attachment`, `contentType: application/pdf`. Find it via
  `GET /users/<uid>/items/<parentKey>/children`.
- Download: `GET https://api.zotero.org/users/<uid>/items/<attachmentKey>/file`
  with header `Zotero-API-Key: <key>` → raw bytes (zip-deflate PDF). Verified
  working for `28H8BQST` → child `NTWRI8PI`.
- Creds already exist at `CommonerLLP/twenty27/secrets/zotero.env`
  (`ZOTERO_API_KEY`, `ZOTERO_USER_ID=1691836`, group `6566614`); rotate at
  <https://www.zotero.org/settings/keys>. Pick a canonical home for these
  (config, not a sibling repo's secrets/) as part of this work.
- **Resolve the attachment key first.** Local files live at
  `storage_path/<ATTACHMENT_key>/<filename>`, **not** under the parent item key.
  Get the child key from local `zotero.sqlite` (`itemAttachments`) or the Web API
  `children` call before touching the filesystem.
- **Storage modes differ.** `imported_file`/`imported_url` → bytes exist locally
  under the attachment key once synced, **and** are retrievable via Web API `/file`
  (the fallback when not yet synced). `linked_file` → no Web API blob; only the
  local linked path. Prefer **local-first**, Web API as fallback. Handle all three.

## Success criteria

1. A CLI command (mirror `place-cli-scope.md` conventions) and an MCP tool, e.g.
   `partial-recall fetch <item_key> [--corpus zotero] [--text|--path] [--json]`:
   - `--path`: ensure the file is local (download to a cache dir if needed), print
     the path. Idempotent; cache keyed by item/attachment key.
   - `--text`: print **clean, reading-order** text (see #2).
2. **Column-aware extraction.** Two-column PDFs must come out in reading order
   (`pdftotext -layout`, or PyMuPDF `get_text("blocks")` sorted by column then y).
   The Teltumbde Misra sentence must read straight. A regression test should pin a
   known two-column fixture.
3. **Local-first resolution.** Resolves parent→attachment-child key and serves the
   file from `storage_path` with no network call when present; uses the Web API
   `/file` blob only as the fallback for genuinely-remote/unsynced attachments.
4. `--json` payload shape stable enough for `jq` (e.g. `.item_key, .path,
   .content_type, .source` = `web|local`).
5. A test exists and passes.

## The bigger fix this exposes (flag, decide separately)

The scrambling isn't just a retrieval-display problem — the **chunker embedded the
scrambled text**, so every two-column PDF in the index has degraded vectors. A
column-aware extraction pass at **index time** would improve recall quality across
the whole corpus, not just on-demand reads. That's a larger re-index decision for
`ROADMAP.md`, not this command — but this scope is where it surfaced, so note it
there.

## Out of scope here

- A `zotero_pull.py` inside governingclaste (rejected — DRY; this is why it's here).
- Acquire-gating glue (`acquire-if-new.sh`) — lives in ahara / shared skills, see
  `docs/place-cli-scope.md`.
- Canonicalising where Zotero creds live (note it, but don't let it block the
  command — read from env/config with the twenty27 path as a documented fallback).
