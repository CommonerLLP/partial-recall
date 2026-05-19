"""MCP tool: get_item_details (v0.2.3 C3).

Given an item_key (and optional corpus), return the items-table row
plus a breakdown of how many chunks / which source types exist for it
in the active embedding run. An agent uses this after semantic_search
to "expand" a hit — see the full title, abstract, creators, every
source the chunk came from.

Returns a single TextContent with structured JSON. Returns a clear
error payload (not an exception) when the item is not found, so the
MCP loop survives.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

from partial_recall.store.vector_store import VectorStore

GET_ITEM_DETAILS_TOOL: Tool = Tool(
    name="get_item_details",
    description=(
        "Look up full metadata for a single item by item_key. Returns "
        "title, date, creators, abstract, indexed source types, and "
        "chunk count. Useful after semantic_search to expand a hit "
        "into a citation-ready record."
    ),
    inputSchema={
        "type": "object",
        "required": ["item_key"],
        "properties": {
            "item_key": {
                "type": "string",
                "description": "Stable identifier for the item.",
            },
            "corpus": {
                "type": "string",
                "description": (
                    "Optional corpus name (e.g. 'zotero', 'folder'). "
                    "If omitted, the first matching item across all "
                    "corpora is returned."
                ),
            },
        },
        "additionalProperties": False,
    },
)


async def handle_get_item_details(
    arguments: dict[str, Any],
    *,
    store: VectorStore,
) -> list[TextContent]:
    item_key = (arguments or {}).get("item_key")
    if not item_key or not isinstance(item_key, str):
        return [_error("Missing or invalid 'item_key' (must be a string).")]
    corpus = (arguments or {}).get("corpus")

    item_row = _fetch_item(store, item_key=item_key, corpus=corpus)
    if item_row is None:
        return [_error(
            f"No item found for item_key={item_key!r}"
            + (f" in corpus={corpus!r}" if corpus else " (any corpus)")
        )]

    source_rows = store._conn.execute(
        """
        SELECT source_type, COUNT(*) AS n
        FROM chunks
        WHERE corpus = ? AND item_key = ?
        GROUP BY source_type
        """,
        (item_row["corpus"], item_row["item_key"]),
    ).fetchall()
    source_breakdown = {row["source_type"]: int(row["n"]) for row in source_rows}
    chunk_total = sum(source_breakdown.values())

    active = store.get_active_run()
    vector_total_active_run: int | None = None
    if active is not None:
        vector_total_active_run = int(store._conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM vectors v
            JOIN chunks c ON c.chunk_id = v.chunk_id
            WHERE v.run_id = ?
              AND c.corpus = ?
              AND c.item_key = ?
            """,
            (active.run_id, item_row["corpus"], item_row["item_key"]),
        ).fetchone()["n"])

    payload = {
        "item": {
            "item_key": item_row["item_key"],
            "corpus": item_row["corpus"],
            "item_type": item_row["item_type"],
            "title": item_row["title"],
            "date": item_row["date"],
            "creators": _safe_json(item_row["creators_json"]),
            "abstract": item_row["abstract"],
            "last_indexed_at": item_row["last_indexed_at"],
            "corpus_ref": item_row["corpus_ref"],
        },
        "chunks": {
            "total": chunk_total,
            "by_source_type": source_breakdown,
        },
        "active_run": (
            {
                "run_id": active.run_id,
                "vectors_for_this_item": vector_total_active_run,
            }
            if active is not None
            else None
        ),
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


def _fetch_item(
    store: VectorStore, *, item_key: str, corpus: str | None
) -> Any:
    if corpus:
        return store._conn.execute(
            """
            SELECT item_key, corpus, item_type, title, date, creators_json,
                   abstract, last_indexed_at, corpus_ref
            FROM items
            WHERE corpus = ? AND item_key = ?
            LIMIT 1
            """,
            (corpus, item_key),
        ).fetchone()
    return store._conn.execute(
        """
        SELECT item_key, corpus, item_type, title, date, creators_json,
               abstract, last_indexed_at, corpus_ref
        FROM items
        WHERE item_key = ?
        LIMIT 1
        """,
        (item_key,),
    ).fetchone()


def _safe_json(raw: str | None) -> Any:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _error(message: str) -> TextContent:
    return TextContent(
        type="text",
        text=json.dumps({"error": message}, indent=2),
    )
