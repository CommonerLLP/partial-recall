"""MCP tool: search_fulltext (v0.2.4 C2).

Keyword / phrase search across chunk previews via SQLite FTS5. Pairs
with semantic_search: an agent uses search_fulltext when it needs to
find an *exact phrase* (a quotation, a title fragment, a citation key)
that semantic embeddings would smooth over.

Behaviour:
  - Operates on the chunks_fts virtual table (schema migration 0002).
  - Returns ranked hits with rank score from FTS5's `bm25(chunks_fts)`.
  - Each hit includes the item-level metadata an agent needs to cite.
  - Supports optional `corpus` filter.
  - Returns a structured error payload (never raises) when the
    underlying FTS5 query is malformed or the table is missing.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from mcp.types import TextContent, Tool

from partial_recall.store.vector_store import VectorStore

SEARCH_FULLTEXT_TOOL: Tool = Tool(
    name="search_fulltext",
    description=(
        "Exact-phrase / keyword search across chunk previews via "
        "SQLite FTS5. Use this when you need to find a specific "
        "quotation, title, or citation key that semantic search "
        "would smooth over. Returns ranked hits with item metadata."
    ),
    inputSchema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "FTS5 query string. Supports phrase queries "
                    "(\"exact phrase\"), AND/OR/NOT operators, "
                    "and prefix matches (word*)."
                ),
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
                    "Optional filter: only search this corpus "
                    "(e.g., 'zotero', 'folder'). Omit for all."
                ),
            },
        },
        "additionalProperties": False,
    },
)


async def handle_search_fulltext(
    arguments: dict[str, Any],
    *,
    store: VectorStore,
) -> list[TextContent]:
    args = arguments or {}
    query = args.get("query")
    if not query or not isinstance(query, str):
        return [_error("Missing or invalid 'query' (must be a string).")]

    top_k = args.get("top_k", 10)
    if not isinstance(top_k, int) or top_k < 1:
        top_k = 10
    top_k = min(top_k, 100)

    corpus = args.get("corpus")

    try:
        rows = _run_fts_query(
            store, query=query, top_k=top_k, corpus=corpus,
        )
    except sqlite3.OperationalError as e:
        # Two likely failures: malformed FTS5 query syntax, or the
        # chunks_fts table not existing (DB at pre-0002 schema). Both
        # are user-visible errors and should not crash the MCP loop.
        return [_error(
            f"FTS5 query failed: {e}. Check the query syntax "
            "(e.g. quote phrases) or confirm the index has been "
            "migrated to schema 2+ via `partial-recall status`."
        )]

    payload: dict[str, Any] = {
        "query": query,
        "top_k": top_k,
        "corpus_filter": corpus,
        "result_count": len(rows),
        "results": [
            {
                "rank": idx + 1,
                "score": float(row["bm25"]) if row["bm25"] is not None else None,
                "chunk_id": int(row["chunk_id"]),
                "item_key": row["item_key"],
                "corpus": row["corpus"],
                "source_type": row["source_type"],
                "source_ref": row["source_ref"],
                "text_preview": row["text_preview"],
                "title": row["title"],
                "date": row["date"],
                # Only when populated (#41). A multi-volume hit needs the
                # volume to be citable; a single-volume one stays compact.
                **{n: row[n] for n in _BIB_FIELDS if row[n]},
            }
            for idx, row in enumerate(rows)
        ],
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


_BIB_FIELDS = (
    "volume",
    "edition",
    "series",
    "series_number",
    "number_of_volumes",
    "publisher",
    "place",
)


def _run_fts_query(
    store: VectorStore,
    *,
    query: str,
    top_k: int,
    corpus: str | None,
) -> list[Any]:
    # bm25() returns a NEGATIVE relevance score (smaller is more
    # relevant); we ORDER BY bm25 ASC so the best hit comes first,
    # then expose the raw score so an agent can read it.
    base_sql = """
        SELECT
            bm25(chunks_fts) AS bm25,
            c.chunk_id        AS chunk_id,
            c.item_key        AS item_key,
            c.corpus          AS corpus,
            c.source_type     AS source_type,
            c.source_ref      AS source_ref,
            c.text_preview    AS text_preview,
            i.title           AS title,
            i.date            AS date,
            i.volume            AS volume,
            i.edition           AS edition,
            i.series            AS series,
            i.series_number     AS series_number,
            i.number_of_volumes AS number_of_volumes,
            i.publisher         AS publisher,
            i.place             AS place
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.rowid
        LEFT JOIN items i
            ON i.owner = 'local'
           AND i.corpus = c.corpus
           AND i.item_key = c.item_key
        WHERE chunks_fts MATCH ?
    """
    params: list[Any] = [query]
    if corpus:
        base_sql += " AND c.corpus = ?"
        params.append(corpus)
    base_sql += " ORDER BY bm25 ASC LIMIT ?"
    params.append(top_k)
    return store._conn.execute(base_sql, params).fetchall()


def _error(message: str) -> TextContent:
    return TextContent(
        type="text",
        text=json.dumps({"error": message}, indent=2),
    )
