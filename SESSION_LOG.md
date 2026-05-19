# SESSION_LOG — partial-recall

Append-only session history. New entries at top.

---

## 2026-05-18 — v0.2.3 shipped (MCP tool surface + canonical leak-check)

- v0.2.3 tagged on `origin/main`. Adds two MCP tools — `semantic_status`
  (zero-arg index status: counts, corpus breakdown, active embedding-run
  metadata) and `get_item_details` (full item metadata + active-run
  chunk/vector counts by source_type). C2 `search_fulltext` (FTS5)
  deferred to v0.2.4 because it needs schema migration 0002 + auto-
  migration support for existing DBs.
- Adopted canonical `scripts/check_leaks.py` from sansad-semantic-crawler
  (two-source pattern design: PUBLIC_PATTERNS committed + per-machine
  patterns in `notes/leak-patterns.txt` gitignored). Replaces the
  bash-based scan that shipped earlier in v0.2.3.
- Canonical copies of `check_leaks.py` + `leak-check.yml` placed at
  `_org/scripts/` and `_org/templates/` as single source of truth
  for CommonerLLP-wide propagation. Tracked org-wide rollout to
  academiaindia, theright2read, budget-crawler as follow-up.
- 217 tests passing on the v0.2.3 commit; 6/6 CI cells green
  (macOS-14, Ubuntu-22.04, Windows-2022 × Python 3.11, 3.12).
- Codex review (P2): `get_item_details` chunk counts scoped to
  active embedding run for consistency with the `active_run`
  vector count; fallback to all-chunks when no active run exists.

## 2026-05-18 — v0.2.2 shipped (resumable indexing)

- v0.2.2 tagged. B4 + B5: pipeline writes `indexing_progress` per
  item boundary; SIGINT / SIGTERM handler converts to clean stop
  returning `IndexResult(interrupted=True, last_processed_key=…)`
  instead of raising. Resume safely re-walks every item; chunk-level
  `vector_exists` keeps embedding cost zero on already-done work.
- Codex P1 review caught an unsafe fast-skip-by-item-key on resume —
  removed; correctness comes from chunk-level dedup, not adapter
  ordering assumptions. Regression test added against an out-of-
  order adapter (B, D, A, C — interrupt after D; A must still embed
  on resume).

## 2026-05-18 — v0.2.1 shipped (reliability foundation)

- v0.2.1 tagged. Cross-platform CI matrix in place: macOS-14 +
  Ubuntu-22.04 + Windows-2022 × Python 3.11, 3.12. Caught a Windows
  path-separator bug in FolderAdapter on the first run (POSIX `/`
  vs `\` in `.partial-recallignore` patterns).
- vcrpy + pytest-recording infrastructure for Gemini cassettes:
  `@pytest.mark.vcr` plus an auto-skip-when-cassette-missing fixture
  so CI replays the moment cassettes land. Cassettes themselves
  deferred (need a real Gemini key to record).
- Log-sanitization processor (A4) gained value-shape redaction:
  Gemini / GitHub / OpenAI / JWT / PEM key shapes are redacted
  regardless of field name. Caught by the new CI gate test that
  exercises the real structlog pipeline end-to-end.

## 2026-05-18 — v0.2.0 shipped (top-up indexing + Zotero notes/annotations + FolderAdapter + doctor)

- v0.2.0 tagged. Sliceable first step in the v0.2.x line — about a
  third of the originally-planned 18-item v0.2.0 scope. The rest is
  sequenced across v0.2.1 through v0.2.5 in ROADMAP.
- Top-up indexing: `index --extend` / `--extend-run RUN_ID` /
  `--allow-provider-mismatch`. Vector-space compatibility enforced;
  provider/model identity is waivable for the cookjohn-imported →
  fresh-Gemini bridge.
- ZoteroAdapter gained notes + annotations (textual types 1 / 2 / 5).
- FolderAdapter: recursive walk over a directory tree; PDF/TXT/MD;
  `.partial-recallignore` support.
- `doctor` command with 9 named diagnostic checks (incl. macOS
  UF_HIDDEN-on-.pth which actually fired against a real user setup).
- Indexer UX overhaul: determinate progress bar with current-item
  title, time-remaining estimate, plain-English explainers, pypdf
  noise filter with humanised end-of-run summary.
- PDF crash defence — single malformed PDF (missing `/Root` Catalog,
  mid-iter cross-reference exhaustion) skips that item instead of
  killing the whole run.
- Log-sanitization processor and `--limit` / `-n` alias on `search`.

## 2026-05-18 — post-release cleanup

- Fast-forwarded `main` to `release/v0.1.0`; tagged `v0.1.0` on the
  release commit and pushed the tag.
- PR #3 merged: enabled the Gemini provider option in the `init`
  first-run wizard (it had been wired since v0.0.1 but left disabled
  in the wizard with a stale "[coming in v0.1.0]" label); reconciled
  `ROADMAP.md` against the actual source tree (v0.0.1 marked complete;
  v0.1.0 rescoped to what shipped — Gemini provider + small CLI
  polish on top of v0.0.1); the originally-planned feature-complete
  scope moved to a new v0.2.0 section; later releases renumbered.
- Drafted v0.2.0 design spec at
  `docs/superpowers/specs/2026-05-18-partial-recall-v0.2.0-design.md`
  (18 items across 5 workstreams: reliability foundation, indexing
  completeness, MCP tool surface, operability, audience reach).
- Tightened branch protection on `main`: `enforce_admins: true`,
  linear history required, conversation resolution required. Direct
  pushes to `main` (including by admins) now blocked.
- Tagged `v0.0.9` retroactively on commit `0d45c6e` and pushed
  (the v0.0.9 release branch had been merged but never tagged).
- Pruned merged release branches from origin (`release/v0.0.9`,
  `release/v0.1.0`); deleted the same locally along with the stale
  local-only `chore/v020-spec-and-session-log`. Origin now carries
  only `main` plus the two release tags.

## 2026-05-17 — v0.0.1

Initial public release.
