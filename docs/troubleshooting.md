# Troubleshooting

Things that actually went wrong in development of v0.2.0 → v0.2.4,
each with the fix that made them stop. Read this before opening an
issue.

## `command not found: partial-recall` <a id="path"></a>

`pipx` installed it but your shell can't find it.

```zsh
pipx ensurepath
# then open a new shell, OR:
source ~/.zshrc        # or ~/.bashrc
```

If still missing: `ls ~/.local/bin/partial-recall` — if the file
is there, `~/.local/bin` is not on your PATH.

## "No Gemini API key found" but I exported the env var

The Gemini provider's resolution order is **keyring → env vars**.
If you've stored a key in the OS keyring previously and exported a
different env var, the keyring wins (deliberate: a stale env var
shouldn't override a configured keyring entry).

Check the source:

```zsh
partial-recall doctor
# → embedding_provider: ok (provider=gemini ...); API key from keyring
# OR                                              ; API key from env var
```

To delete the keyring entry: `partial-recall keyring delete-gemini`.
To pick env over keyring: delete the keyring entry, then export your
env var.

## "DB schema version N < expected" — v0.2.3 → v0.2.4 upgrade

v0.2.4 introduced auto-migration. An existing v0.2.3 DB
(schema_version = 1) gets schema 0002 (FTS5) and 0003 (Zotero
richness) applied forward automatically on first `connect()`.
If you see this error from a v0.2.4 install, your install ISN'T
actually v0.2.4. Check:

```zsh
partial-recall --version
# → partial-recall 0.2.4 (or later)
```

If it says < 0.2.4: `pipx upgrade partial-recall`.

## pypdf spits "Ignoring wrong pointing object …" lines during `index`

Expected. These are pypdf's WARNING-level reports that a PDF had a
malformed cross-reference table but pypdf recovered by scanning
linearly. Common in academic PDFs that went through OCR / merge /
linearise cycles. Text still extracts; nothing is being skipped.
At end of run you'll see a humanised summary like:

```
Recovered text from PDFs with structural issues (7 total recovery events):
  • 5 × malformed cross-reference table
  • 2 × broken font character map
This is normal — text extraction succeeded.
```

If a specific PDF is so broken pypdf can't open it at all, v0.2.0+
skips that one item instead of crashing the whole run.

## `partial-recall index` ran for 30 minutes then died on one bad PDF

Pre-v0.2.0 behaviour. You're on an old install. Upgrade:

```zsh
pipx upgrade partial-recall
```

v0.2.0+ catches `PdfReadError` during `iter(reader.pages)` (the
"no /Root Catalog" class) and skips the item.

## After re-index, my `--extend` run was about to embed everything again

The previous active embedding run's `provider` / `model_name` may
not match your current config — e.g. you imported via cookjohn
(`provider='cookjohn-imported'`) and your config now says `gemini`.
Use:

```zsh
partial-recall index --extend --allow-provider-mismatch
```

Vector-space fields (dimensions, quantization, normalized,
distance_metric) are still enforced — the flag only waives
provider+model identity. Chunk-level vector_exists dedup kicks in,
so already-vectorised chunks are skipped at zero Gemini cost.

## macOS: editable install can't import `partial_recall`

You'll see `ModuleNotFoundError: No module named 'partial_recall'`
when running from the venv. Run `partial-recall doctor` and look at
`pth_uf_hidden`:

```
✗ pth_uf_hidden — N .pth file(s) in site-packages are marked UF_HIDDEN
  hint: chflags -R nohidden …/site-packages/*.pth
```

This is iCloud Drive's "Desktop & Documents" sync marking your venv's
`.pth` files hidden. Python's site.py respects the macOS hidden flag
and skips them. Two durable fixes:

1. Move the venv out of `~/Documents/` (e.g. to `~/.local/share/venvs/`).
2. Disable iCloud sync for the Documents folder.

`chflags nohidden` works as a one-shot fix but iCloud re-hides the
files within minutes.

## "No collections shown" in `list_collections` MCP tool

Three possible causes, in order of likelihood:

1. You haven't run `partial-recall index --source zotero` since
   upgrading to v0.2.4. The collections sync runs at the end of
   `index`; until you do that, the `collections` table is empty.
2. Your Zotero library genuinely has no user-defined collections.
3. Your `[zotero]` source is disabled or pointing at a different
   `sqlite_path` than the one with collections.

## `Aakash's 29,937-item personal Zotero library` shows up in old commits

Pre-v0.2.4 ROADMAP leaked personal-corpus markers. History was
rewritten on 2026-05-18; the scrubbed history is what's on origin
today. If you cloned in the leak window (between the v0.2.0 commit
and the rewrite), force a fresh fetch:

```zsh
git fetch origin
git reset --hard origin/main
```

## CI complains about `__pycache__` in `partial_recall/secrets/`

The `.gitignore` `secrets/` rule (meant for credential files) once
swept up the `partial_recall.secrets` source package. v0.2.4
narrowed the exception to `*.py` files only; `__pycache__/` stays
ignored. If you see this on a fork or older branch, sync to current
`.gitignore`.

## I want to use partial-recall offline / on a plane

That's the default. With `[embedding] provider = "local-onnx"` and
any `[folder]` corpus, partial-recall makes zero network calls.
The Gemini provider is opt-in; everything else is local.

Caveats:
- First run downloads the ONNX model (~470 MB). Do this once with a
  network; subsequent runs are offline.
- `partial-recall init` doesn't need network.
- The MCP server is over stdio (`partial-recall serve`); no network
  port involved.
