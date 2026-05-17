"""`partial-recall index` — build / update the vector index."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from partial_recall.config.loader import load_config
from partial_recall.config.models import EmbeddingProviderName
from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.errors import (
    ConfigError,
    CorpusUnavailableError,
    PartialRecallError,
)
from partial_recall.index.pipeline import run_indexing
from partial_recall.paths import config_path
from partial_recall.store.vector_store import VectorStore

console = Console()


def _build_provider(
    provider_name: EmbeddingProviderName, model: str
) -> EmbeddingProvider:
    if provider_name == "local-onnx":
        # Lazy import — avoid loading ONNX deps unless local-onnx selected
        from partial_recall.embedding.providers.local_onnx import LocalONNXProvider

        return LocalONNXProvider(model_name=model)
    if provider_name == "gemini":
        from partial_recall.embedding.providers.gemini import GeminiAPIProvider

        return GeminiAPIProvider(model_name=model)
    raise PartialRecallError(f"Unknown embedding provider: {provider_name}")


def index_command(
    config: Path = typer.Option(  # noqa: B008 — Typer pattern
        None,
        "--config",
        help="Path to config.toml (default: platform default).",
    ),
    source: str = typer.Option(  # noqa: B008
        "zotero",
        "--source",
        help="Which corpus adapter to use. v0.0.1: only 'zotero'.",
    ),
) -> None:
    """Build or update the vector index from the configured corpus.

    v0.0.1: only 'zotero' source is supported. Indexes PDFs + abstracts.
    """
    cfg_path = config if config else config_path()
    if not cfg_path.exists():
        raise ConfigError(
            f"config not found at {cfg_path}; run `partial-recall init` first"
        )
    cfg = load_config(cfg_path)

    if source != "zotero":
        raise PartialRecallError(
            f"Source '{source}' not supported in v0.0.1 (only 'zotero')."
        )
    if not cfg.zotero.enabled:
        raise PartialRecallError(
            "Zotero source is disabled in config. "
            "Set [zotero] enabled = true and re-run."
        )
    if not cfg.zotero.sqlite_path.exists():
        raise CorpusUnavailableError(
            f"Zotero DB not found at {cfg.zotero.sqlite_path}. "
            "Check your config or re-run `partial-recall init`."
        )

    console.print(
        f"[bold]Loading embedding provider:[/bold] "
        f"{cfg.embedding.provider} ({cfg.embedding.model})"
    )
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        load_task = progress.add_task(
            "Loading ONNX model (first run downloads ~470 MB)...", total=None
        )
        provider = _build_provider(cfg.embedding.provider, cfg.embedding.model)
        progress.remove_task(load_task)

    console.print(f"[bold]Opening Zotero:[/bold] {cfg.zotero.sqlite_path}")
    adapter = ZoteroAdapter(
        sqlite_path=cfg.zotero.sqlite_path,
        storage_path=cfg.zotero.storage_path,
    )
    console.print(f"[bold]Opening vector store:[/bold] {cfg.index.vector_db_path}")
    store = VectorStore(cfg.index.vector_db_path)

    console.print("\n[bold]Indexing...[/bold]")
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Indexing corpus...", total=None)
            result = run_indexing(
                adapter=adapter,  # type: ignore[arg-type]
                store=store,
                provider=provider,
            )
            progress.update(task, completed=1)
    finally:
        adapter.close()
        provider.close()

    console.print(
        f"\n[green]✓[/green] Indexed [bold]{result.item_count}[/bold] items, "
        f"[bold]{result.chunk_count}[/bold] chunks, "
        f"[bold]{result.new_vector_count}[/bold] new vectors "
        f"(run_id={result.run_id})"
    )
    store.close()
