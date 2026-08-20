"""`partial-recall index` — build / update the vector index."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

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
from partial_recall.corpus.protocol import CorpusAdapter
from partial_recall.corpus.registry import BUILTIN_ADAPTER_NAMES, create_adapter
from partial_recall.corpus.types import Item
from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.errors import (
    ConfigError,
    PartialRecallError,
)
from partial_recall.extract.pdf_noise import PypdfNoiseFilter
from partial_recall.index.pipeline import IncompatibleRunError, run_indexing
from partial_recall.paths import config_path
from partial_recall.store.index_lock import IndexLock
from partial_recall.store.vector_store import VectorStore


def _truncate_title(title: str | None, fallback: str, width: int = 60) -> str:
    text = (title or "").strip() or fallback
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"

console = Console()


class _ZoteroCollectionsAdapter(Protocol):
    def list_zotero_collections(self) -> Iterator[dict]: ...

    def list_collection_memberships(self) -> Iterator[dict]: ...


def _sync_zotero_collections(
    adapter: _ZoteroCollectionsAdapter, store: VectorStore
) -> None:
    """Mirror Zotero's collections + memberships into our store.

    Cheap to re-run on every `index`; gives the MCP `list_collections`
    tool + the `get_item_details` collection-list a fresh snapshot.
    """
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat(timespec="seconds")
    collection_count = 0
    for collection in adapter.list_zotero_collections():
        store.upsert_collection(
            corpus="zotero",
            collection_key=collection["collection_key"],
            name=collection["name"],
            parent_key=collection.get("parent_key"),
            last_indexed_at=now,
        )
        collection_count += 1

    # Wipe stale memberships before re-inserting (codex P2 review on
    # PR #13). The collections + item_collections tables become an
    # authoritative mirror of what Zotero currently says — an item
    # removed from a collection (or a deleted collection) doesn't
    # linger.
    cleared = store.clear_collection_memberships("zotero")

    membership_count = 0
    for edge in adapter.list_collection_memberships():
        # Skip edges whose item_key was not upserted in this run (e.g.
        # an attachment or note that the adapter's list_items filter
        # excludes). Without this guard the FK insert would fail.
        # We check by looking up items table for the (corpus, item_key).
        if not _item_exists(store, "zotero", edge["item_key"]):
            continue
        store.link_item_to_collection(
            corpus="zotero",
            item_key=edge["item_key"],
            collection_key=edge["collection_key"],
        )
        membership_count += 1
    console.print(
        f"[bold]Collections:[/bold] synced {collection_count} collection(s); "
        f"cleared {cleared} stale memberships; wrote {membership_count} fresh edge(s)."
    )


def _item_exists(store: VectorStore, corpus: str, item_key: str) -> bool:
    row = store._conn.execute(
        "SELECT 1 FROM items WHERE owner = 'local' AND corpus = ? AND item_key = ? LIMIT 1",
        (corpus, item_key),
    ).fetchone()
    return row is not None


def _build_provider(
    provider_name: EmbeddingProviderName, model: str, device: str = "auto"
) -> EmbeddingProvider:
    if provider_name == "local-onnx":
        # Lazy import — avoid loading ONNX deps unless local-onnx selected
        from partial_recall.embedding.providers.local_onnx import LocalONNXProvider

        return LocalONNXProvider(model_name=model)
    if provider_name == "gemini":
        from partial_recall.embedding.providers.gemini import GeminiAPIProvider

        return GeminiAPIProvider(model_name=model)
    if provider_name == "sentence-transformer":
        from partial_recall.embedding.providers.sentence_transformer import (
            SentenceTransformerProvider,
        )

        return SentenceTransformerProvider(model_name=model, device=device)
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
        help=(
            "Corpus adapter. Built-ins: "
            + ", ".join(BUILTIN_ADAPTER_NAMES)
            + ". Or use a dotted path like package.module:AdapterClass."
        ),
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
    rescan: bool = typer.Option(  # noqa: B008
        False,
        "--rescan",
        help=(
            "When extending: extract every source again, even one whose "
            "chunks all have a vector already. Use it after editing a file "
            "in place. Extend mode otherwise skips those sources, because "
            "re-extracting them cannot produce new work."
        ),
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

    # Fail fast before the expensive setup below (ONNX model load, store
    # open/migration) when another index process is already writing to
    # this DB. run_indexing holds the real lock for the run itself.
    IndexLock(cfg.index.vector_db_path).probe()

    console.print(f"[bold]Loading corpus adapter:[/bold] {source}")
    adapter: CorpusAdapter = create_adapter(source, cfg)

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
        provider = _build_provider(
            cfg.embedding.provider, cfg.embedding.model, cfg.embedding.device
        )
        progress.remove_task(load_task)

    console.print(f"[bold]Opening vector store:[/bold] {cfg.index.vector_db_path}")
    store = VectorStore(cfg.index.vector_db_path)

    # (Zotero collections sync now happens AFTER run_indexing — items
    # must exist in the items table before item_collections rows can
    # FK-link to them. Caught by codex P1 review on PR #13.)

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
    pdf_noise = None
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
                    rescan=rescan,
                    on_item_start=_on_item_start,
                )
            except IncompatibleRunError as e:
                raise PartialRecallError(str(e)) from e
            progress.update(
                task,
                completed=result.item_count,
                description="Finished",
            )

        # Plain-English summary of any pypdf recovery noise.
        if pdf_noise is not None and pdf_noise.total > 0:
            console.print(f"\n[dim]{pdf_noise.human_summary()}[/dim]")

        if result.extended:
            console.print(
                f"\n[green]✓[/green] Extended run_id={result.run_id}: "
                f"walked [bold]{result.item_count}[/bold] items, "
                f"added [bold]{result.chunk_count}[/bold] new chunks, "
                f"embedded [bold]{result.new_vector_count}[/bold] new vectors, "
                f"skipped [bold]{result.skipped_chunk_count}[/bold] already-vectorised"
                f" chunks, skipped extraction on "
                f"[bold]{result.skipped_source_count}[/bold] covered sources"
            )
        else:
            console.print(
                f"\n[green]✓[/green] Indexed [bold]{result.item_count}[/bold] items, "
                f"[bold]{result.chunk_count}[/bold] chunks, "
                f"[bold]{result.new_vector_count}[/bold] new vectors "
                f"(run_id={result.run_id})"
            )

        # Sync collections + memberships AFTER run_indexing so items already
        # exist in the items table (FK target for item_collections).
        # Folder corpus does not have a collections concept.
        if source == "zotero":
            _sync_zotero_collections(adapter, store)

    finally:
        adapter.close()
        provider.close()

    store.close()
