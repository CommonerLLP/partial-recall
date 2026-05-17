"""`partial-recall import cookjohn` — one-shot migration from cookjohn vectors."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Confirm
from rich.table import Table

from partial_recall.config.loader import load_config
from partial_recall.errors import (
    ConfigError,
    CorpusUnavailableError,
)
from partial_recall.importers.cookjohn import import_cookjohn
from partial_recall.paths import config_path
from partial_recall.store.vector_store import VectorStore

console = Console()

import_app = typer.Typer(
    name="import",
    help="One-shot migrations from other vector stores.",
    no_args_is_help=True,
)


@import_app.command(
    name="cookjohn",
    help="Import vectors from cookjohn/zotero-mcp's vectors.sqlite.",
)
def cookjohn_command(
    source: Path = typer.Option(  # noqa: B008
        ...,
        "--source",
        "-s",
        help="Path to cookjohn's zotero-mcp-vectors.sqlite",
    ),
    config: Path = typer.Option(  # noqa: B008
        None,
        "--config",
        help="Path to config.toml (default: platform default).",
    ),
    no_activate: bool = typer.Option(  # noqa: B008
        False,
        "--no-activate",
        help="Do not mark the imported run active. Default: prompt.",
    ),
    yes: bool = typer.Option(  # noqa: B008
        False,
        "--yes",
        "-y",
        help="Skip the activation prompt and activate the new run.",
    ),
) -> None:
    """Import cookjohn/zotero-mcp's existing vectors into partial-recall.

    This is a one-shot migration — partial-recall does NOT depend on cookjohn
    at runtime. After import, you can search via `partial-recall search` or
    via the MCP server (`partial-recall serve`).
    """
    source = source.expanduser().resolve()
    if not source.exists():
        raise CorpusUnavailableError(f"cookjohn DB not found at {source}")

    cfg_path = config if config else config_path()
    if not cfg_path.exists():
        raise ConfigError(
            f"config not found at {cfg_path}; run `partial-recall init` first"
        )
    cfg = load_config(cfg_path)

    zotero_path: Path | None = (
        cfg.zotero.sqlite_path if cfg.zotero.enabled else None
    )
    if zotero_path is not None and not zotero_path.exists():
        console.print(
            f"[yellow]warning: configured Zotero DB not found at "
            f"{zotero_path}; items will be imported without title/author "
            f"enrichment.[/yellow]"
        )
        zotero_path = None

    console.print(f"[bold]Source:[/bold] {source}")
    console.print(f"[bold]Vector DB:[/bold] {cfg.index.vector_db_path}")
    if zotero_path:
        console.print(f"[bold]Zotero metadata:[/bold] {zotero_path}")
    else:
        console.print("[dim]Zotero metadata enrichment: disabled[/dim]")

    store = VectorStore(cfg.index.vector_db_path)

    try:
        # Decide activation policy:
        # --no-activate → never activate
        # --yes → activate without prompt
        # otherwise → prompt after import
        will_activate_now = not no_activate and yes

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Importing cookjohn vectors...", total=None
            )
            first_total: dict[str, int | None] = {"value": None}

            def cb(processed: int, total: int) -> None:
                if first_total["value"] is None:
                    first_total["value"] = total
                    progress.update(task, total=total)
                progress.update(task, completed=processed)

            result = import_cookjohn(
                cookjohn_path=source,
                zotero_path=zotero_path,
                store=store,
                activate=will_activate_now,
                progress_callback=cb,
            )

        # Summary table
        t = Table(title="Cookjohn import complete", show_header=False, box=None)
        t.add_column("Key", style="bold")
        t.add_column("Value")
        t.add_row("Run ID:", str(result.run_id))
        t.add_row("Items imported:", f"{result.item_count:,}")
        t.add_row("Chunks created:", f"{result.chunk_count:,}")
        t.add_row("Vectors written:", f"{result.vector_count:,}")
        console.print(t)

        # If neither --yes nor --no-activate, prompt now.
        if not no_activate and not yes:
            should_activate = Confirm.ask(
                f"\nActivate this run (run_id={result.run_id}) for searching?",
                default=True,
            )
            if should_activate:
                store.activate_run(result.run_id)
                console.print(
                    f"[green]✓[/green] Run {result.run_id} activated."
                )
            else:
                console.print(
                    f"[dim]Run {result.run_id} left inactive. "
                    f"Use `partial-recall runs activate {result.run_id}` "
                    f"later to enable it for search.[/dim]"
                )
        elif no_activate:
            console.print(
                f"[dim]Run {result.run_id} left inactive "
                f"(per --no-activate).[/dim]"
            )
        else:
            console.print(
                f"[green]✓[/green] Run {result.run_id} activated."
            )
    finally:
        store.close()
