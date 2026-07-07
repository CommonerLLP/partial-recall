"""MCP tool: semantic_search.

Wraps partial_recall.search.orchestrator.search and serialises the results
into the JSON shape defined in design spec §9.3.

v0.0.1 implements the `query`, `top_k`, `corpus`, and `min_score` filters.
The `item_types`, `source_types`, `locale`, `date_from`, and `date_to`
filters are advertised in the input schema so MCP clients know they are
coming, but are deferred to v0.1.0.
"""

from __future__ import annotations

import json
import time
from typing import Any

from mcp.types import TextContent, Tool

from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.errors import PartialRecallError
from partial_recall.search.orchestrator import SearchResult, search
from partial_recall.store.vector_store import VectorStore

SEMANTIC_SEARCH_TOOL: Tool = Tool(
    name="semantic_search",
    description=(
        "Search the user's scholarly corpus by semantic similarity. "
        "Returns ranked chunks with item metadata."
    ),
    inputSchema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language query. Can be multilingual.",
            },
            "top_k": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "description": "Maximum number of results to return.",
            },
            "corpus": {
                "type": "string",
                "description": (
                    "Optional filter: only search this corpus. Any corpus name "
                    "present in the index is valid (built-in adapters like "
                    "'zotero', 'folder', 'markdown_notes', 'jabref', 'calibre' "
                    "as well as external-adapter corpora). Use semantic_status "
                    "to list the corpora in this index. Omit for all."
                ),
            },
            "item_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional filter: only return these item types. "
                    "Deferred to v0.1.0."
                ),
            },
            "source_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["pdf", "note", "annotation", "metadata", "abstract", "epub"],
                },
                "description": (
                    "Optional filter: only return these source types. "
                    "Deferred to v0.1.0."
                ),
            },
            "locale": {
                "type": "string",
                "description": (
                    "Optional filter: only return chunks with this detected locale "
                    "(e.g., 'tam' for Tamil). Detection is best-effort; short or "
                    "mixed-language chunks may be misclassified. Deferred to v0.1.0."
                ),
            },
            "min_score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Optional minimum cosine similarity (0.0-1.0) "
                    "to filter low-relevance results."
                ),
            },
        },
    },
)


def _serialise_result(r: SearchResult) -> dict[str, Any]:
    """Convert a SearchResult into the JSON shape from design spec §9.3."""
    return {
        "rank": r.rank,
        "score": round(r.score, 4),
        "item_key": r.item_key,
        "corpus": r.corpus,
        "item": {
            "type": r.item_type,
            "title": r.title,
            "creators": r.creators,
            "date": r.date,
            "abstract": r.abstract,
        },
        "source": {
            "type": r.source_type,
            "ref": r.source_ref,
            "preview": r.text_preview,
        },
        "chunk": {
            "id": r.chunk_id,
            "index": r.chunk_index,
            "char_offset": [r.char_offset_start, r.char_offset_end],
            "locale": r.detected_locale,
            "chunker_version": "recursive-char-1024-128-v1",
        },
    }


async def handle_semantic_search(
    arguments: dict[str, Any],
    *,
    store: VectorStore,
    provider: EmbeddingProvider,
) -> list[TextContent]:
    """Handle a semantic_search MCP tool call.

    Returns a single TextContent whose `text` is a JSON document with the
    `results` and `query_metadata` keys (per design spec §9.3). On error,
    `text` is a JSON object with `error` and `hint` keys, allowing MCP
    clients to surface the failure cleanly without an exception.
    """
    query = arguments.get("query")
    if not query or not isinstance(query, str):
        return [TextContent(
            type="text",
            text=json.dumps(
                {"error": "Missing or invalid 'query' argument.",
                 "hint": "Provide a non-empty string as 'query'."},
                indent=2,
            ),
        )]

    top_k_raw = arguments.get("top_k", 10)
    try:
        top_k = int(top_k_raw)
    except (TypeError, ValueError):
        top_k = 10
    top_k = max(1, min(100, top_k))

    corpus_filter = arguments.get("corpus")
    min_score_raw = arguments.get("min_score")
    min_score: float | None
    try:
        min_score = float(min_score_raw) if min_score_raw is not None else None
    except (TypeError, ValueError):
        min_score = None

    started = time.perf_counter()
    try:
        results = search(
            store=store,
            provider=provider,
            query=query,
            top_k=top_k,
            corpus=corpus_filter,
        )
    except PartialRecallError as exc:
        return [TextContent(
            type="text",
            text=json.dumps(
                {"error": str(exc) or exc.__class__.__name__,
                 "hint": exc.actionable_hint or "See partial-recall logs for details."},
                indent=2,
            ),
        )]
    except Exception as exc:  # defensive: never crash the MCP loop
        return [TextContent(
            type="text",
            text=json.dumps(
                {"error": f"{exc.__class__.__name__}: {exc}",
                 "hint": "Unexpected error; see partial-recall logs."},
                indent=2,
            ),
        )]

    # corpus is pre-filtered in the search layer; only min_score remains here.
    filtered: list[SearchResult] = []
    for r in results:
        if min_score is not None and r.score < min_score:
            continue
        filtered.append(r)

    # Re-rank after filtering so client-visible `rank` is contiguous.
    serialised = [
        _serialise_result(SearchResult(
            rank=i,
            score=r.score,
            item_key=r.item_key,
            corpus=r.corpus,
            item_type=r.item_type,
            title=r.title,
            date=r.date,
            creators=r.creators,
            abstract=r.abstract,
            source_type=r.source_type,
            source_ref=r.source_ref,
            chunk_id=r.chunk_id,
            chunk_index=r.chunk_index,
            char_offset_start=r.char_offset_start,
            char_offset_end=r.char_offset_end,
            text_preview=r.text_preview,
            detected_locale=r.detected_locale,
        ))
        for i, r in enumerate(filtered, start=1)
    ]

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    active = store.get_active_run()
    query_metadata = {
        "embedding_provider": active.provider if active else None,
        "embedding_model": active.model_name if active else None,
        "active_run_id": active.run_id if active else None,
        "elapsed_ms": elapsed_ms,
    }

    payload = {
        "results": serialised,
        "query_metadata": query_metadata,
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2, ensure_ascii=False))]
