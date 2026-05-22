"""Search orchestrator.

Takes a query string, embeds it via the active embedding run's provider,
calls VectorStore.top_k_int8, enriches with item metadata, returns ranked
SearchResult list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.errors import IndexNotReadyError
from partial_recall.store.vector_store import SearchHit, VectorStore


@dataclass(frozen=True)
class SearchResult:
    """One ranked search hit with enriched item metadata."""
    rank: int
    score: float
    item_key: str
    corpus: str
    item_type: str
    title: str | None
    date: str | None
    creators: list[dict[str, str]]
    abstract: str | None
    source_type: str
    source_ref: str | None
    chunk_id: int
    chunk_index: int
    char_offset_start: int | None
    char_offset_end: int | None
    text_preview: str | None
    detected_locale: str | None


def search(
    *,
    store: VectorStore,
    provider: EmbeddingProvider,
    query: str,
    top_k: int = 10,
    corpus: str | None = None,
) -> list[SearchResult]:
    """Run a semantic search against the active embedding run.

    Raises IndexNotReadyError if no active embedding run exists.
    """
    active = store.get_active_run()
    if active is None:
        raise IndexNotReadyError("No active embedding run; run `partial-recall index` first.")

    # Embed the query (use the 'search_query' task hint for asymmetric models)
    batch = provider.embed([query], task="search_query")
    if batch.vectors is None or not batch.vectors:
        return []
    query_vec = batch.vectors[0]

    hits: list[SearchHit] = store.top_k_int8(
        run_id=active.run_id,
        query_vector=query_vec,
        k=top_k,
        corpus=corpus,
    )
    if not hits:
        return []

    # Enrich with item metadata
    item_keys = [h.item_key for h in hits]
    corpus_values = list({h.corpus for h in hits})
    if not item_keys:
        return []
    # Build SQL: items keyed by (owner='local', corpus, item_key)
    placeholders = ",".join("?" * len(item_keys))
    corpus_placeholders = ",".join("?" * len(corpus_values))
    item_rows = store._conn.execute(
        f"""SELECT corpus, item_key, item_type, title, date, creators_json, abstract
            FROM items
            WHERE corpus IN ({corpus_placeholders})
              AND item_key IN ({placeholders})""",  # noqa: S608
        list(corpus_values) + list(item_keys),
    ).fetchall()
    item_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for row in item_rows:
        item_by_key[(row["corpus"], row["item_key"])] = {
            "item_type": row["item_type"],
            "title": row["title"],
            "date": row["date"],
            "creators": json.loads(row["creators_json"]) if row["creators_json"] else [],
            "abstract": row["abstract"],
        }

    results: list[SearchResult] = []
    for rank, h in enumerate(hits, start=1):
        meta = item_by_key.get((h.corpus, h.item_key), {})
        creators_raw = meta.get("creators", [])
        creators_typed: list[dict[str, str]] = (
            creators_raw if isinstance(creators_raw, list) else []
        )
        results.append(SearchResult(
            rank=rank,
            score=h.score,
            item_key=h.item_key,
            corpus=h.corpus,
            item_type=str(meta.get("item_type", "")),
            title=meta.get("title"),  # type: ignore[arg-type]
            date=meta.get("date"),  # type: ignore[arg-type]
            creators=creators_typed,
            abstract=meta.get("abstract"),  # type: ignore[arg-type]
            source_type=h.source_type,
            source_ref=h.source_ref,
            chunk_id=h.chunk_id,
            chunk_index=h.chunk_index,
            char_offset_start=h.char_offset_start,
            char_offset_end=h.char_offset_end,
            text_preview=h.text_preview,
            detected_locale=h.detected_locale,
        ))
    return results
