# Scope of work — `partial-recall place` CLI

> Authored 2026-06-18 from an **ahara** session (sister tool). Drop-in spec for the
> next partial-recall agent. Read `docs/ARCHITECTURE.md` and `docs/discovery.md`
> first; claim scope in `WORKING.md` before editing code.

## One-line goal

Expose the existing **positioning** capability (`place_item`) as a CLI command —
`partial-recall place` — so it can be called from a plain shell script, not only
through the MCP stdio server.

## Why (the consuming workflow)

ahara fetches licensed e-books and files them into Zotero; partial-recall reads
Zotero (read-only) and indexes it. We want an **acquire-gating** step: *before*
ahara fetches a candidate, ask partial-recall "do I already own this / does it
fill a gap?" and only fetch the gap-fillers.

Today that check is **only possible from an MCP client** — positioning is
`place_item` (MCP-stdio only). The CLI has `index/search/status/serve/...` but
**no `place`**, and `serve` is stdio MCP (not HTTP), so a shell script cannot
reach it. This command closes that gap. The downstream glue (a cross-repo
`acquire-if-new.sh` that calls `partial-recall place` then `ahara get`) lives in
ahara / shared skills and is **out of scope here**.

## Success criteria

1. `partial-recall place --title "<t>" [--blurb "<b>"] [--corpus zotero] [--top-k N] [--json]`
   runs and prints a placement.
2. `--json` emits **the same payload shape** as the `place_item` MCP tool, so the
   same `jq` filters work against both. At minimum:
   `.placement.{density, top_score, mean_score, related_count, likely_owned, owned_match}`.
3. Human (non-`--json`) mode prints a short summary: density, `likely_owned`,
   and the top neighbours (mirror `search`'s table style).
4. `--corpus` scopes the "owned" judgement to one corpus (so `--corpus zotero`
   answers "is this in my Zotero library", not the folder/news corpora).
5. A CLI test exists and passes.

## Implementation anchors (do NOT re-derive — reuse)

- **Positioning already exists.** Call
  `partial_recall.discovery.positioning.position(store, provider, title, blurb, top_k, corpus)`
  → returns the `Positioning` dataclass
  (`density` ∈ {empty,thin,moderate,dense}, `top_score`, `mean_score`,
  `related_count`, `likely_owned`, `owned_match`, neighbours).
  Thresholds live there: `LIKELY_OWNED_THRESHOLD=0.97`, `DENSE_TOP=0.86`,
  `MODERATE_TOP=0.78`. **Do not reimplement any of this.**
- **The MCP tool is the reference implementation.**
  `src/partial_recall/mcp/tools/place_item.py` → `handle_place_item` already
  validates args, calls `position(...)`, and builds the JSON payload. Mirror its
  output dict exactly so MCP and CLI stay in lockstep.
- **Mirror `cli/search.py` for plumbing.** `search_command` shows the pattern:
  `load_config` → `_build_provider(provider_name, model)` → open `VectorStore`
  → run → `--json` vs rich table. Copy that construction; swap `search()` for
  `position()`.
- **Register like the others** in `cli/app.py`:
  `app.command(name="place", help="Position a candidate work against the corpus.")(place_command)`.
  New file: `src/partial_recall/cli/place.py` with `place_command`.

## CLI interface

```
partial-recall place --title TITLE [--blurb TEXT] [--corpus NAME]
                     [--top-k N (default 10)] [--json]
```
- `--title` required; `--blurb` optional (improves accuracy, same as MCP).
- `--corpus` optional; when omitted, match `place_item`'s default behaviour.
- Exit non-zero with a clear message on config/index/provider errors
  (reuse `PartialRecallError`; mirror `search`'s error handling).

## Constraints (org rules)

- **Read-only.** Like every other Zotero-facing path here — no writes to Zotero,
  no index mutation. Positioning only reads the vector store + embeds the query.
- **DRY.** Reuse `position()` and the search CLI plumbing; this should be a thin
  (~20–40 line) wrapper + a test, not new logic.
- **Single source of truth for output.** If the MCP payload and CLI JSON drift,
  the cross-repo jq filters break. Keep them identical (consider extracting the
  payload-builder into a shared helper both call, if cheap).

## Out of scope

- The ahara-side wrapper script / acquire-gating glue (lives in ahara or shared
  skills).
- Any change to the `place_item` MCP tool's behaviour.
- HTTP transport for `serve`. Any Zotero write-back.

## Acceptance tests

- `partial-recall place --corpus zotero --json --title "<a book known to be in the library>"`
  → `.placement.likely_owned == true`.
- `--title "<novel/absent topic>"` → `.placement.density` is `empty`/`thin`,
  `likely_owned == false`.
- CLI `--json` payload keys match `place_item`'s payload (snapshot/contract test).
- Add `tests/test_cli_place.py` mirroring `tests/test_cli_index.py` /
  `test_cli_doctor.py` (fixture store + fake provider; assert JSON shape and the
  density/likely_owned logic for an owned vs novel title).

## Effort

Small. `position()` and the search-CLI plumbing already exist; this is a wrapper
command + registration + one test.

## Decision table the consumer applies (context, not your job to build)

| place result | meaning | ahara action |
|---|---|---|
| `likely_owned: true` | near-identical already indexed | skip |
| `density: empty`/`thin` | opens a gap | acquire |
| `density: moderate` | complements holdings | acquire |
| `density: dense` | already well-read | defer |
