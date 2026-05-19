"""`partial-recall doctor` — diagnostic command (v0.2.0 D1).

Catalogue of failure modes encountered while bringing v0.0.1 → v0.2.0
into shape. Each check returns an OK / WARN / FAIL with a plain-English
description and, where possible, an actionable hint.

Today's known failures this catches:

  * No `PARTIAL_RECALL_GEMINI_API_KEY` in environment when provider=gemini.
  * Vector-store missing or unreachable.
  * Active embedding run's provider/model differs from the configured
    provider — the cookjohn-imported → fresh-Gemini mismatch.
  * Zotero DB missing or locked.
  * Folder source enabled but paths empty or missing.
  * macOS: venv .pth files silently marked UF_HIDDEN by iCloud Drive
    on Documents-synced repos (breaks editable installs).
  * Python version too old for partial-recall (3.11+).
  * Config file unreadable or malformed.

Each addition to this list is a small win — failures stop hitting users
in tracebacks and start showing up as named checks.
"""

from __future__ import annotations

import platform
import shutil
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from partial_recall.config.loader import load_config
from partial_recall.paths import config_path
from partial_recall.store.vector_store import VectorStore

console = Console()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "ok" | "warn" | "fail" | "skip"
    message: str
    hint: str | None = None


CheckFn = Callable[[], CheckResult]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_python_version() -> CheckResult:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        return CheckResult(
            name="python_version",
            status="fail",
            message=f"Python {major}.{minor} is too old; partial-recall needs 3.11+.",
            hint="Install Python 3.11 or newer; re-install partial-recall under it.",
        )
    return CheckResult(
        name="python_version",
        status="ok",
        message=f"Python {major}.{minor}.{sys.version_info[2]} (>= 3.11).",
    )


def _check_config_present(cfg_path: Path) -> CheckResult:
    if not cfg_path.exists():
        return CheckResult(
            name="config_present",
            status="fail",
            message=f"Config file not found at {cfg_path}.",
            hint="Run `partial-recall init` to create it.",
        )
    try:
        load_config(cfg_path)
    except Exception as e:  # noqa: BLE001 — surface any config-parse failure
        return CheckResult(
            name="config_present",
            status="fail",
            message=f"Config at {cfg_path} could not be parsed: {e}",
            hint="Check the TOML for syntax errors, or back it up and re-run "
                 "`partial-recall init`.",
        )
    return CheckResult(
        name="config_present",
        status="ok",
        message=f"Config readable at {cfg_path}.",
    )


def _check_embedding_provider(cfg) -> CheckResult:
    provider = cfg.embedding.provider
    if provider == "gemini":
        # v0.2.4: resolve via secrets module (keyring → env vars).
        from partial_recall.secrets import get_gemini_api_key
        key = get_gemini_api_key()
        if not key:
            return CheckResult(
                name="embedding_provider",
                status="fail",
                message="provider=gemini but no API key is configured "
                        "(neither in OS keyring nor in "
                        "PARTIAL_RECALL_GEMINI_API_KEY / GEMINI_API_KEY).",
                hint="Store it with `partial-recall keyring set-gemini` "
                     "(uses Keychain / Secret Service / Credential "
                     "Manager) or export PARTIAL_RECALL_GEMINI_API_KEY "
                     "in your shell.",
            )
        # Soft check on shape — Gemini keys look like "AIzaSy..." (39 chars).
        if not key.startswith("AIzaSy") or len(key) < 35:
            return CheckResult(
                name="embedding_provider",
                status="warn",
                message="A Gemini API key is configured but its shape does "
                        "not match the expected 'AIzaSy…' / 39-character "
                        "pattern.",
                hint="Verify the key is correct; the API call will fail at "
                     "first use if it's malformed.",
            )
        # Indicate WHERE the key was found so a user knows whether
        # they're on the keyring path or the env-var path.
        from partial_recall.secrets import GEMINI_KEYRING_KEY, _keyring_get
        source = "keyring" if _keyring_get(GEMINI_KEYRING_KEY) else "env var"
        return CheckResult(
            name="embedding_provider",
            status="ok",
            message=f"provider=gemini ({cfg.embedding.model}); API key from {source}.",
        )
    if provider == "local-onnx":
        try:
            import onnxruntime  # noqa: F401
            import tokenizers  # noqa: F401
        except ImportError as e:
            return CheckResult(
                name="embedding_provider",
                status="fail",
                message=f"provider=local-onnx but a required dep is missing: {e}.",
                hint="pipx install --force partial-recall[local]  "
                     "OR pip install -e '.[local]' inside your venv.",
            )
        return CheckResult(
            name="embedding_provider",
            status="ok",
            message=f"provider=local-onnx ({cfg.embedding.model}); deps importable.",
        )
    return CheckResult(
        name="embedding_provider",
        status="warn",
        message=f"Unknown provider={provider!r}. No diagnostic available.",
    )


def _check_vector_store(cfg) -> CheckResult:
    path = cfg.index.vector_db_path
    if not path.exists():
        return CheckResult(
            name="vector_store",
            status="warn",
            message=f"Vector store not found at {path} — no indexing has run yet.",
            hint="This is expected before your first `partial-recall index`.",
        )
    try:
        store = VectorStore(path)
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            name="vector_store",
            status="fail",
            message=f"Vector store at {path} could not be opened: {e}",
            hint="If the file is small/empty, deleting it and re-running "
                 "`index` will rebuild. Back up first.",
        )
    try:
        runs = store.list_runs()
        active = store.get_active_run()
    finally:
        store.close()
    if not runs:
        return CheckResult(
            name="vector_store",
            status="warn",
            message=f"Vector store at {path} has no embedding runs yet.",
            hint="Run `partial-recall index` to create the first run.",
        )
    if active is None:
        return CheckResult(
            name="vector_store",
            status="warn",
            message=f"Vector store has {len(runs)} run(s) but no active one.",
            hint="Activate one with `partial-recall runs activate <run_id>` "
                 "(command lands in v0.2.x).",
        )
    return CheckResult(
        name="vector_store",
        status="ok",
        message=f"Vector store OK; active run_id={active.run_id} "
                f"(provider={active.provider}, model={active.model_name}, "
                f"dim={active.dimensions}).",
    )


def _check_active_run_matches_config(cfg) -> CheckResult:
    path = cfg.index.vector_db_path
    if not path.exists():
        return CheckResult(
            name="run_matches_config",
            status="skip",
            message="No vector store yet — nothing to compare against.",
        )
    try:
        store = VectorStore(path)
        active = store.get_active_run()
        store.close()
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            name="run_matches_config",
            status="skip",
            message=f"Could not read vector store: {e}.",
        )
    if active is None:
        return CheckResult(
            name="run_matches_config",
            status="skip",
            message="No active run to compare against.",
        )
    if active.provider != cfg.embedding.provider:
        return CheckResult(
            name="run_matches_config",
            status="warn",
            message=f"Active run provider={active.provider!r} differs from "
                    f"config provider={cfg.embedding.provider!r}.",
            hint="If you mean to extend the existing run, pass "
                 "`--allow-provider-mismatch` to `index --extend`. Otherwise "
                 "start a fresh run.",
        )
    if active.model_name != cfg.embedding.model:
        return CheckResult(
            name="run_matches_config",
            status="warn",
            message=f"Active run model={active.model_name!r} differs from "
                    f"config model={cfg.embedding.model!r}.",
            hint="A model change implies a re-embed for new chunks. Consider "
                 "running a fresh `index` (no --extend) and switching the "
                 "active run when done.",
        )
    return CheckResult(
        name="run_matches_config",
        status="ok",
        message="Active embedding run matches config provider + model.",
    )


def _check_zotero_source(cfg) -> CheckResult:
    if not cfg.zotero.enabled:
        return CheckResult(
            name="zotero_source",
            status="skip",
            message="Zotero source disabled in config.",
        )
    p = cfg.zotero.sqlite_path
    if not p.exists():
        return CheckResult(
            name="zotero_source",
            status="fail",
            message=f"Zotero DB not found at {p}.",
            hint="Update [zotero] sqlite_path or disable [zotero] enabled.",
        )
    # Try a read-only probe.
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True, timeout=2)
        conn.execute("SELECT 1 FROM items LIMIT 1").fetchone()
        conn.close()
    except sqlite3.OperationalError as e:
        return CheckResult(
            name="zotero_source",
            status="warn",
            message=f"Zotero DB at {p} could not be opened read-only: {e}",
            hint="Close Zotero and try again, or the adapter will fall back "
                 "to zotero.sqlite.bak if present.",
        )
    return CheckResult(
        name="zotero_source",
        status="ok",
        message=f"Zotero DB readable at {p}.",
    )


def _check_folder_source(cfg) -> CheckResult:
    if not cfg.folder.enabled:
        return CheckResult(
            name="folder_source",
            status="skip",
            message="Folder source disabled in config.",
        )
    if not cfg.folder.paths:
        return CheckResult(
            name="folder_source",
            status="fail",
            message="Folder source enabled but [folder] paths is empty.",
            hint="Set paths = ['/path/to/library/'] in config.toml.",
        )
    missing = [p for p in cfg.folder.paths if not Path(p).exists()]
    if missing:
        return CheckResult(
            name="folder_source",
            status="fail",
            message=f"Folder paths do not exist: {[str(p) for p in missing]}.",
            hint="Fix the paths in config, or remove them.",
        )
    return CheckResult(
        name="folder_source",
        status="ok",
        message=f"All {len(cfg.folder.paths)} folder path(s) exist.",
    )


def _check_pth_uf_hidden() -> CheckResult:
    """macOS-only: verify no .pth file in the running venv carries the
    UF_HIDDEN flag (iCloud's silent saboteur of editable installs)."""
    if platform.system() != "Darwin":
        return CheckResult(
            name="pth_uf_hidden",
            status="skip",
            message="UF_HIDDEN check only applies to macOS.",
        )
    # Find the active venv's site-packages by walking sys.prefix.
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = Path(sys.prefix) / "lib" / py_ver / "site-packages"
    if not site_packages.exists():
        return CheckResult(
            name="pth_uf_hidden",
            status="skip",
            message=f"Could not locate site-packages under {sys.prefix}.",
        )
    hidden: list[Path] = []
    for pth in site_packages.glob("*.pth"):
        try:
            st = pth.lstat()
        except OSError:
            continue
        if getattr(st, "st_flags", 0) & 0x8000:  # UF_HIDDEN
            hidden.append(pth)
    if hidden:
        return CheckResult(
            name="pth_uf_hidden",
            status="fail",
            message=f"{len(hidden)} .pth file(s) in site-packages are marked "
                    f"UF_HIDDEN; editable installs will silently fail to import.",
            hint=f"Run: chflags -R nohidden {site_packages}/*.pth  — and if "
                 "the venv lives under ~/Documents/ (iCloud-synced), move it "
                 "out (e.g. to ~/.local/share/venvs/<name>) so the flag does "
                 "not return.",
        )
    return CheckResult(
        name="pth_uf_hidden",
        status="ok",
        message=f"All .pth files in {site_packages.name} are visible.",
    )


def _check_disk_space(cfg) -> CheckResult:
    db_path = cfg.index.vector_db_path
    target = db_path.parent if db_path.parent.exists() else Path.home()
    try:
        free = shutil.disk_usage(target).free
    except OSError as e:
        return CheckResult(
            name="disk_space",
            status="warn",
            message=f"Could not check free space on {target}: {e}",
        )
    free_gb = free / (1024 ** 3)
    if free_gb < 1.0:
        return CheckResult(
            name="disk_space",
            status="fail",
            message=f"Only {free_gb:.2f} GB free on {target}; indexing needs "
                    f"headroom (~310 MB per 15K-item corpus).",
            hint="Free up disk before running `index`.",
        )
    if free_gb < 5.0:
        return CheckResult(
            name="disk_space",
            status="warn",
            message=f"{free_gb:.1f} GB free on {target} — usable but tight.",
        )
    return CheckResult(
        name="disk_space",
        status="ok",
        message=f"{free_gb:.1f} GB free on {target}.",
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_all_checks(cfg_path: Path | None = None) -> list[CheckResult]:
    """Run every diagnostic and return the list, in display order."""
    cp = cfg_path if cfg_path else config_path()
    results: list[CheckResult] = [_check_python_version()]
    results.append(_check_config_present(cp))
    # If config didn't load, downstream checks are uninformative.
    try:
        cfg = load_config(cp)
    except Exception:  # noqa: BLE001
        results.append(CheckResult(
            name="downstream",
            status="skip",
            message="Skipping remaining checks — config did not load.",
        ))
        return results
    results.append(_check_embedding_provider(cfg))
    results.append(_check_vector_store(cfg))
    results.append(_check_active_run_matches_config(cfg))
    results.append(_check_zotero_source(cfg))
    results.append(_check_folder_source(cfg))
    results.append(_check_pth_uf_hidden())
    results.append(_check_disk_space(cfg))
    return results


_STATUS_STYLE = {
    "ok":   ("[green]✓[/green]", "green"),
    "warn": ("[yellow]![/yellow]", "yellow"),
    "fail": ("[red]✗[/red]",     "red"),
    "skip": ("[dim]·[/dim]",     "dim"),
}


def doctor_command(
    config: Path = typer.Option(  # noqa: B008
        None, "--config", help="Path to config.toml (default: platform default).",
    ),
    json_output: bool = typer.Option(  # noqa: B008
        False, "--json", help="Emit structured JSON to stdout instead of a table.",
    ),
) -> None:
    """Run diagnostic checks against your partial-recall install.

    Each check returns one of:
      ✓ ok    — pass
      ! warn  — works but worth noting
      ✗ fail  — something is wrong; the hint explains how to fix it
      · skip  — not applicable (e.g. folder check when folder is disabled)

    Exit status is non-zero if any check fails.
    """
    results = run_all_checks(config)

    if json_output:
        import json
        payload = [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "hint": r.hint,
            }
            for r in results
        ]
        typer.echo(json.dumps(payload, indent=2))
    else:
        table = Table(title="partial-recall diagnostic checks", show_lines=False)
        table.add_column("", width=2)
        table.add_column("check")
        table.add_column("status")
        table.add_column("message", overflow="fold")
        for r in results:
            icon, _style = _STATUS_STYLE.get(r.status, ("?", ""))
            msg = r.message
            if r.hint:
                msg += f"\n[dim]hint: {r.hint}[/dim]"
            table.add_row(icon, r.name, r.status, msg)
        console.print(table)

    if any(r.status == "fail" for r in results):
        raise typer.Exit(code=1)
