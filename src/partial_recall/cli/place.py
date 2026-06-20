"""`partial-recall place` — candidate work positioning from the CLI."""

from __future__ import annotations

import json as json_lib
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from partial_recall.cli.search import _build_provider
from partial_recall.config.loader import load_config
from partial_recall.discovery.positioning import build_place_payload, position
from partial_recall.errors import ConfigError
from partial_recall.paths import config_path
from partial_recall.store.vector_store import VectorStore

console = Console()

def place_command(
    title: str = typer.Option(  # noqa: B008
        ...,
        "--title", "-t",
        help="Title of the candidate work (with subtitle if any).",
    ),
    blurb: str = typer.Option(  # noqa: B008
        None,
        "--blurb", "-b",
        help="Optional abstract, jacket blurb, or description. Improves positioning accuracy.",
    ),
    corpus: str = typer.Option(  # noqa: B008
        None,
        "--corpus", "-c",
        help=(
            "Restrict the neighbourhood to one corpus (e.g. 'zotero'). "
            "Omit to position against everything."
        ),
    ),
    top_k: int = typer.Option(  # noqa: B008
        10,
        "--limit", "-n",
        "--top-k", "-k",
        help="Number of nearest neighbours to return.",
    ),
    config: Path = typer.Option(  # noqa: B008
        None,
        "--config",
        help="Path to config.toml (default: platform default).",
    ),
    json_output: bool = typer.Option(  # noqa: B008
        False,
        "--json",
        help="Emit structured JSON to stdout (machine-readable).",
    ),
) -> None:
    """Position a candidate work against the corpus."""
    cfg_path = config if config else config_path()
    if not cfg_path.exists():
        raise ConfigError(
            f"config not found at {cfg_path}; run `partial-recall init` first"
        )
    cfg = load_config(cfg_path)

    provider = _build_provider(cfg.embedding.provider, cfg.embedding.model)
    store = VectorStore(cfg.index.vector_db_path)
    active = store.get_active_run()
    
    try:
        placement = position(
            store=store,
            provider=provider,
            title=title,
            blurb=blurb,
            top_k=top_k,
            corpus=corpus,
        )

        if json_output:
            payload = build_place_payload(placement, active)
            sys.stdout.write(json_lib.dumps(payload, ensure_ascii=False, indent=2))
            sys.stdout.write("\n")
            return

        # Human-readable output
        console.print(f"[bold]Placement for:[/bold] {placement.query_text[:100]}...")
        console.print(f"Density: [bold cyan]{placement.density}[/bold cyan]")
        color = "green" if placement.likely_owned else "yellow"
        console.print(f"Likely Owned: [bold {color}]{placement.likely_owned}[/]")
        console.print("")

        if not placement.neighbours:
            console.print("[yellow]No neighbours found.[/yellow]")
            return
            
        t = Table(title="Nearest Neighbours")
        t.add_column("#", style="dim", width=3)
        t.add_column("Score", style="cyan", width=7)
        t.add_column("Corpus", style="magenta", width=10)
        t.add_column("Title", style="bold", overflow="fold", max_width=50)
        t.add_column("Authors", style="dim italic", overflow="fold", max_width=22)
        
        for i, r in enumerate(placement.neighbours, 1):
            t_title = (r.title or "(no title)")[:130]
            
            def _fmt(c: dict) -> str:
                last = c.get("last") or ""
                first = c.get("first") or ""
                initial = f", {first[:1]}." if first else ""
                return last + initial
                
            authors = "; ".join(
                _fmt(c) for c in (r.creators or [])[:3]
            ) or "—"
            
            t.add_row(
                str(i), f"{r.score:.3f}", r.corpus, t_title, authors
            )
        console.print(t)

    finally:
        store.close()
        provider.close()
