**Repo:** partial-recall

**Progress:**
- ROADMAP: 68 / 115 items shipped
- TODO: 13 completed, 10 pending

**Integrity:** ✅ `uv run ruff check .` and `uv run pytest -q -m "not live and not slow"` pass.

**Blockers:** None

**Commit gap:** staged: 14 | unstaged: 0 | untracked: 0 | branch: chore/repo-hygiene-recovery

**Verdict:** On track. Repo hygiene, lint, and non-live test integrity are green on the recovery branch. The binding constraint to the next gate is deciding on the v0.3.1 scope (Faiss / HTTP) and completing the discovery follow-ups.

**Live Ops:** N/A (CLI tool)
