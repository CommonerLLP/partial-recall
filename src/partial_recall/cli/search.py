"""`partial-recall search QUERY` — direct semantic search from the CLI.

Output modes:
- default: rich human-readable table with Zotero deep-links
- --json: structured JSON to stdout (machine-readable; pipeable to jq)
- --bibliography: deduplicated-by-item view (v0.1.0; not yet implemented)
"""

from __future__ import annotations

import json as json_lib
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from partial_recall.config.loader import load_config
from partial_recall.config.models import EmbeddingProviderName
from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.errors import ConfigError, PartialRecallError
from partial_recall.paths import config_path
from partial_recall.search.orchestrator import SearchResult, search
from partial_recall.store.vector_store import VectorStore

console = Console()


def _build_provider(
    provider_name: EmbeddingProviderName, model: str
) -> EmbeddingProvider:
    if provider_name == "local-onnx":
        from partial_recall.embedding.providers.local_onnx import LocalONNXProvider

        return LocalONNXProvider(model_name=model)
    if provider_name == "gemini":
        from partial_recall.embedding.providers.gemini import GeminiAPIProvider

        return GeminiAPIProvider(model_name=model)
    raise PartialRecallError(f"Unknown embedding provider: {provider_name}")


def _zotero_uri(item_key: str, corpus: str) -> str | None:
    """Zotero deep-link URI for clickable open-in-Zotero behavior.

    Only emit for Zotero-corpus items; future corpora (folder, obsidian, IIIF)
    get None.
    """
    if corpus == "zotero":
        return f"zotero://select/library/items/{item_key}"
    return None


def _humanize_source(result: SearchResult) -> str:
    """Render a human-friendly source label.

    Cookjohn-imported chunks have opaque internal chunk-ids (`pdf:cookjohn:42`)
    that aren't useful to read. Hide those; show just the source type.
    PDF chunks indexed by partial-recall's own pipeline will have page-number
    refs (v0.1.0); show them when present.
    """
    if not result.source_ref:
        return result.source_type
    if result.source_ref.startswith(("cookjohn:", "pdf:cookjohn:")):
        return result.source_type  # hide the opaque cookjohn chunk id
    # e.g. 'pdf:p=12' or 'note:KEYXX' — show as-is, it's user-meaningful
    return result.source_ref


def _result_to_dict(r: SearchResult) -> dict:
    """Serialize a SearchResult for the JSON output mode."""
    return {
        "rank": r.rank,
        "score": round(r.score, 4),
        "item_key": r.item_key,
        "corpus": r.corpus,
        "zotero_uri": _zotero_uri(r.item_key, r.corpus),
        "item": {
            "type": r.item_type,
            "title": r.title,
            "date": r.date,
            "creators": r.creators,
            "abstract": r.abstract,
        },
        "source": {
            "type": r.source_type,
            "ref": r.source_ref,
            "human_ref": _humanize_source(r),
            "preview": r.text_preview,
        },
        "chunk": {
            "id": r.chunk_id,
            "index": r.chunk_index,
            "char_offset_start": r.char_offset_start,
            "char_offset_end": r.char_offset_end,
            "detected_locale": r.detected_locale,
        },
    }


def search_command(
    query: str = typer.Argument(..., help="Natural-language query."),  # noqa: B008
    top_k: int = typer.Option(  # noqa: B008
        10,
        "--limit", "-n",
        "--top-k", "-k",
        help="Number of results to return.",
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
    """Run a semantic search from the terminal.

    Default output is a human-readable rich table. Pass --json for
    machine-readable structured output (pipeable to jq, etc.).
    """
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
        results = search(store=store, provider=provider, query=query, top_k=top_k)

        if json_output:
            # Machine-readable: structured JSON on stdout. Human output suppressed.
            payload = {
                "query": query,
                "top_k": top_k,
                "result_count": len(results),
                "query_metadata": {
                    "embedding_provider": cfg.embedding.provider,
                    "embedding_model": cfg.embedding.model,
                    "active_run_id": active.run_id if active else None,
                    "vector_dim": active.dimensions if active else None,
                },
                "results": [_result_to_dict(r) for r in results],
            }
            sys.stdout.write(json_lib.dumps(payload, ensure_ascii=False, indent=2))
            sys.stdout.write("\n")
            return

        # Human-readable: rich table
        if not results:
            console.print("[yellow]No results.[/yellow]")
            return
        t = Table(title=f'partial-recall: top {len(results)} for "{query}"')
        t.add_column("#", style="dim", width=3)
        t.add_column("Score", style="cyan", width=7)
        t.add_column("Date", style="green", width=10)
        t.add_column("Title", style="bold", overflow="fold", max_width=50)
        t.add_column("Authors", style="dim italic", overflow="fold", max_width=22)
        t.add_column("Src", style="dim", width=5)
        t.add_column("Preview", overflow="fold")
        for r in results:
            title = (r.title or "(no title)")[:130]
            date = (r.date or "")[:10]
            def _fmt(c: dict) -> str:
                last = c.get("last") or ""
                first = c.get("first") or ""
                initial = f", {first[:1]}." if first else ""
                return last + initial
            authors = "; ".join(
                _fmt(c) for c in (r.creators or [])[:3]
            ) or "—"
            preview = (r.text_preview or "")[:240].replace("\n", " ")
            src = _humanize_source(r)
            t.add_row(
                str(r.rank), f"{r.score:.3f}", date, title, authors, src, preview
            )
        console.print(t)

        # Print Zotero deep-links below the table for click-to-open
        zotero_items = [r for r in results if r.corpus == "zotero"]
        if zotero_items:
            console.print("\n[bold]Open in Zotero:[/bold]")
            seen: set[str] = set()
            for r in zotero_items:
                if r.item_key in seen:
                    continue
                seen.add(r.item_key)
                uri = _zotero_uri(r.item_key, r.corpus)
                console.print(f"  [{r.rank}] {uri}")
    finally:
        store.close()
        provider.close()
