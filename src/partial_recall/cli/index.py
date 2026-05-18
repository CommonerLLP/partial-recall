"""`partial-recall index` — build / update the vector index."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from partial_recall.config.loader import load_config
from partial_recall.config.models import EmbeddingProviderName
from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.corpus.types import Item
from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.errors import (
    ConfigError,
    CorpusUnavailableError,
    PartialRecallError,
)
from partial_recall.extract.pdf_noise import PypdfNoiseFilter
from partial_recall.index.pipeline import IncompatibleRunError, run_indexing
from partial_recall.paths import config_path
from partial_recall.store.vector_store import VectorStore


def _truncate_title(title: str | None, fallback: str, width: int = 60) -> str:
    text = (title or "").strip() or fallback
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"

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
    extend: bool = typer.Option(  # noqa: B008
        False,
        "--extend",
        help=(
            "Top-up mode: extend the active embedding run with vectors "
            "for chunks it doesn't yet cover (and any new items). "
            "Skips already-vectorised chunks — no re-embedding cost."
        ),
    ),
    extend_run: int | None = typer.Option(  # noqa: B008
        None,
        "--extend-run",
        help="Extend a specific run_id (overrides --extend / active run).",
    ),
    allow_provider_mismatch: bool = typer.Option(  # noqa: B008
        False,
        "--allow-provider-mismatch",
        help=(
            "When extending: skip the provider/model identity check. "
            "Vector-space fields (dimensions, quantization, normalized, "
            "distance_metric) are always enforced. Use when extending a "
            "rehydrated/imported run with a fresh provider that produces "
            "vectors in the same space (e.g. cookjohn-imported → gemini)."
        ),
    ),
) -> None:
    """Build or update the vector index from the configured corpus.

    Default: create a fresh embedding run and embed every chunk into it.

    `--extend`: re-use the active embedding run as the target. Embeds
    only chunks that lack a vector for that run — so a top-up after a
    partial import (e.g. cookjohn rehydrate) costs only the missing
    chunks, not the full corpus.
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

    # Resolve extend target (CLI flag → explicit run → active run).
    target_run_id: int | None = None
    if extend_run is not None:
        target_run_id = extend_run
    elif extend:
        active = store.get_active_run()
        if active is None:
            raise PartialRecallError(
                "--extend requested but no active embedding run exists. "
                "Run without --extend to create the first run."
            )
        target_run_id = active.run_id

    if target_run_id is not None:
        target = store.get_run(target_run_id)
        if target is None:
            raise PartialRecallError(
                f"--extend-run target run_id={target_run_id} not found."
            )
        console.print(
            f"[bold]Extend mode:[/bold] run_id={target.run_id} "
            f"provider={target.provider} model={target.model_name} "
            f"dim={target.dimensions} quant={target.quantization}"
        )
        if allow_provider_mismatch:
            console.print(
                "[yellow]Provider/model identity check waived.[/yellow] "
                "Vector-space fields are still enforced."
            )

    # Count items up-front so the progress bar has a real total. If the
    # adapter can't say (returns None), we fall back to an indeterminate
    # bar with a count-completed display.
    try:
        total_items = adapter.count_items()
    except Exception:  # noqa: BLE001 — non-fatal; just lose determinacy
        total_items = None

    if total_items is not None:
        console.print(
            f"[bold]Walking corpus:[/bold] {total_items} items to consider "
            "(already-indexed chunks will be skipped automatically)"
        )
    console.print(
        "\n[dim]A note on the progress bar's time-remaining estimate: it is "
        "a rough\n"
        "  projection based on the first few items' speed. Actual time "
        "depends on:\n"
        "    • total corpus size (number of items + total PDF text to "
        "extract)\n"
        "    • your internet connection (each batch is a Gemini API call)\n"
        "    • Gemini's rate limits and momentary load on Google's side\n"
        "    • your machine's CPU (PDF text extraction is local + serial)\n"
        "    • the shape of each item (a 500-page scanned book takes far\n"
        "      longer than an abstract or a short annotation)\n"
        "    • how many items are already indexed (those are skipped — fast)\n"
        "  The estimate will get more accurate as the run progresses."
        "[/dim]"
    )
    console.print(
        "\n[dim]A note on PDF warnings: some academic PDFs (scanned, OCR'd, "
        "merged, or\nexported by older software) have small structural "
        "irregularities. partial-recall\nrecovers from these automatically; "
        "you may see a recovery summary at the end.[/dim]\n"
    )

    progress_columns: tuple = (
        TextColumn("[bold blue]{task.description}", justify="left"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
    ) if total_items is not None else (
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
    )

    result = None
    try:
        with PypdfNoiseFilter() as pdf_noise, Progress(
            *progress_columns,
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task(
                "Starting...",
                total=total_items if total_items is not None else None,
            )

            def _on_item_start(item: Item, idx: int, total: int | None) -> None:
                label = _truncate_title(item.title, fallback=item.item_key)
                progress.update(task, completed=idx - 1, description=label)

            try:
                result = run_indexing(
                    adapter=adapter,  # type: ignore[arg-type]
                    store=store,
                    provider=provider,
                    extend_run_id=target_run_id,
                    allow_provider_mismatch=allow_provider_mismatch,
                    on_item_start=_on_item_start,
                )
            except IncompatibleRunError as e:
                raise PartialRecallError(str(e)) from e
            progress.update(
                task,
                completed=result.item_count,
                description="Finished",
            )
    finally:
        adapter.close()
        provider.close()

    # Plain-English summary of any pypdf recovery noise.
    if pdf_noise.total > 0:
        console.print(f"\n[dim]{pdf_noise.human_summary()}[/dim]")

    if result.extended:
        console.print(
            f"\n[green]✓[/green] Extended run_id={result.run_id}: "
            f"walked [bold]{result.item_count}[/bold] items, "
            f"added [bold]{result.chunk_count}[/bold] new chunks, "
            f"embedded [bold]{result.new_vector_count}[/bold] new vectors, "
            f"skipped [bold]{result.skipped_chunk_count}[/bold] already-vectorised"
        )
    else:
        console.print(
            f"\n[green]✓[/green] Indexed [bold]{result.item_count}[/bold] items, "
            f"[bold]{result.chunk_count}[/bold] chunks, "
            f"[bold]{result.new_vector_count}[/bold] new vectors "
            f"(run_id={result.run_id})"
        )
    store.close()
