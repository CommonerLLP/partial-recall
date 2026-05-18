# SESSION_LOG — partial-recall

Append-only session history. New entries at top.

---

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
