"""`partial-recall status` — show index counts, active run, disk usage."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from partial_recall.config.loader import load_config
from partial_recall.errors import ConfigError
from partial_recall.paths import config_path
from partial_recall.store.vector_store import VectorStore

console = Console()


def status_command(
    config: Path = typer.Option(  # noqa: B008
        None,
        "--config",
        help="Path to config.toml (default: platform default).",
    ),
) -> None:
    """Show index status: counts, active run, disk usage."""
    cfg_path = config if config else config_path()
    if not cfg_path.exists():
        raise ConfigError(
            f"config not found at {cfg_path}; run `partial-recall init` first"
        )
    cfg = load_config(cfg_path)

    if not cfg.index.vector_db_path.exists():
        console.print(
            f"[yellow]No vector DB found at {cfg.index.vector_db_path}[/yellow]"
        )
        console.print("Run `partial-recall index` to create it.")
        raise typer.Exit(code=1)

    store = VectorStore(cfg.index.vector_db_path)
    try:
        items = store._conn.execute(
            "SELECT COUNT(*) AS n FROM items"
        ).fetchone()["n"]
        chunks = store._conn.execute(
            "SELECT COUNT(*) AS n FROM chunks"
        ).fetchone()["n"]
        vectors = store._conn.execute(
            "SELECT COUNT(*) AS n FROM vectors"
        ).fetchone()["n"]
        runs = store.list_runs()
        active = store.get_active_run()
        db_size = cfg.index.vector_db_path.stat().st_size

        console.print(
            f"\n[bold]partial-recall index:[/bold] {cfg.index.vector_db_path}\n"
        )
        t = Table(show_header=False, box=None)
        t.add_column("Key", style="bold")
        t.add_column("Value")
        t.add_row("Items:", f"{items:,}")
        t.add_row("Chunks:", f"{chunks:,}")
        t.add_row("Vectors:", f"{vectors:,}")
        t.add_row("Embedding runs:", f"{len(runs)}")
        if active:
            t.add_row(
                "Active run:",
                f"run_id={active.run_id}  provider={active.provider}  "
                f"model={active.model_name}  dim={active.dimensions}",
            )
        else:
            t.add_row("Active run:", "[red]none[/red]")
        t.add_row("DB size:", _human_size(db_size))
        console.print(t)
    finally:
        store.close()


def _human_size(n: int) -> str:
    size: float = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
