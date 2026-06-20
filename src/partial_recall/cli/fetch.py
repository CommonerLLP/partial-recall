import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from partial_recall.config.loader import load_config
from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.corpus.zotero_fetch import fetch_zotero_attachment
from partial_recall.paths import config_path, download_cache_dir

console = Console()

def fetch_command(
    item_key: Annotated[
        str,
        typer.Argument(help="The parent item key (e.g. 28H8BQST)"),
    ],
    config: Path = typer.Option(  # noqa: B008
        None,
        "--config",
        "-c",
        help="Path to partial-recall TOML config.",
    ),
    corpus: str = typer.Option(  # noqa: B008
        "zotero",
        "--corpus",
        help="The corpus to fetch from. Currently only 'zotero' is supported.",
    ),
    text_mode: bool = typer.Option(  # noqa: B008
        False,
        "--text",
        help="Extract and print reading-order text from the PDF.",
    ),
    path_mode: bool = typer.Option(  # noqa: B008
        False,
        "--path",
        help="Print the absolute filesystem path of the resolved file.",
    ),
    json_output: bool = typer.Option(  # noqa: B008
        False,
        "--json",
        help="Output structured JSON instead of human-readable text.",
    ),
) -> None:
    """Fetch an attachment (PDF/EPUB) or its clean text for a given item.

    Resolves the parent item key to its child attachment key, checks local
    storage, and falls back to the Zotero Web API if needed.
    """
    if corpus != "zotero":
        console.print(f"[bold red]Error:[/] Unsupported corpus '{corpus}'. Only 'zotero' is supported.")
        raise typer.Exit(1)

    cfg_path = config if config else config_path()
    if not cfg_path.exists():
        console.print(f"[bold red]Error:[/] config not found at {cfg_path}")
        raise typer.Exit(1)

    cfg = load_config(cfg_path)
    if not cfg.zotero.enabled:
        console.print("[bold red]Error:[/] Zotero is disabled in config.")
        raise typer.Exit(1)

    adapter = ZoteroAdapter(
        sqlite_path=cfg.zotero.sqlite_path,
        storage_path=cfg.zotero.storage_path,
    )
    
    cache_dir = download_cache_dir() / "zotero"

    try:
        res = fetch_zotero_attachment(
            item_key=item_key,
            adapter=adapter,
            config=cfg.zotero,
            cache_dir=cache_dir,
            download_missing=True,
            extract_text=text_mode,
        )
    except Exception as e:
        if json_output:
            console.print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[bold red]Fetch Failed:[/] {e}")
        raise typer.Exit(1)
    finally:
        adapter.close()

    if not res.attachment_key:
        if json_output:
            console.print(json.dumps({"error": "No attachment found"}))
        else:
            console.print(f"[bold yellow]No PDF attachments found for item {item_key}.[/]")
        raise typer.Exit(1)

    if json_output:
        payload = {
            "item_key": res.item_key,
            "attachment_key": res.attachment_key,
            "path": str(res.path.absolute()) if res.path else None,
            "content_type": res.content_type,
            "source": res.source,
        }
        if text_mode:
            payload["text"] = res.text
        import sys
        sys.stdout.write(json.dumps(payload) + "\n")
        return

    # Human-readable output
    console.print(f"[bold]Item:[/] {res.item_key}  [dim](attachment: {res.attachment_key})[/]")
    if res.path:
        console.print(f"[bold]Source:[/] {res.source}")
        if path_mode:
            console.print(f"[bold]Path:[/] {res.path.absolute()}")
        if text_mode:
            console.print("\n[bold]Text Content:[/]")
            console.print("---")
            console.print(res.text or "[dim]No text extracted[/]")
            console.print("---")
    else:
        console.print("[bold red]Error:[/] Could not resolve local or web file.")
