"""MCP tool: semantic_status (v0.2.3 C1).

A Claude session asks "how big is my index?" and gets the same answer
`partial-recall status` gives at the CLI. Useful for:

  * an agent deciding whether a corpus is worth searching at all
  * surfacing version + provider info before issuing semantic_search
  * sanity-checking that the MCP server is wired to the expected DB

The response is a single TextContent containing a structured JSON
payload — counts (items, chunks, vectors), the active embedding run
metadata, schema version, and corpus breakdown.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

from partial_recall.store.vector_store import VectorStore

SEMANTIC_STATUS_TOOL: Tool = Tool(
    name="semantic_status",
    description=(
        "Report current state of the partial-recall index: counts "
        "(items, chunks, vectors); active embedding run (provider, "
        "model, dimensions, quantization); corpus breakdown. No "
        "arguments required. Use this before semantic_search to "
        "decide whether a query is worth issuing."
    ),
    inputSchema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)


async def handle_semantic_status(
    arguments: dict[str, Any],
    *,
    store: VectorStore,
) -> list[TextContent]:
    """Build the status payload and return it as a single TextContent."""
    _ = arguments  # explicit "we know there are no args"

    active = store.get_active_run()
    all_runs = store.list_runs()

    item_total = store._conn.execute(
        "SELECT COUNT(*) AS n FROM items"
    ).fetchone()["n"]
    chunk_total = store._conn.execute(
        "SELECT COUNT(*) AS n FROM chunks"
    ).fetchone()["n"]
    vector_total = store._conn.execute(
        "SELECT COUNT(*) AS n FROM vectors"
    ).fetchone()["n"]

    corpus_rows = store._conn.execute(
        "SELECT corpus, COUNT(*) AS items FROM items GROUP BY corpus"
    ).fetchall()
    corpus_breakdown = {row["corpus"]: int(row["items"]) for row in corpus_rows}

    payload: dict[str, Any] = {
        "schema_version": _read_schema_version(store),
        "totals": {
            "items": int(item_total),
            "chunks": int(chunk_total),
            "vectors": int(vector_total),
        },
        "corpora": corpus_breakdown,
        "embedding_runs": {
            "count": len(all_runs),
            "active": (
                {
                    "run_id": active.run_id,
                    "provider": active.provider,
                    "model_name": active.model_name,
                    "dimensions": active.dimensions,
                    "quantization": active.quantization,
                    "normalized": active.normalized,
                    "distance_metric": active.distance_metric,
                    "chunker_version": active.chunker_version,
                }
                if active is not None
                else None
            ),
        },
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


def _read_schema_version(store: VectorStore) -> int | None:
    try:
        row = store._conn.execute(
            "SELECT schema_version FROM schema_meta LIMIT 1"
        ).fetchone()
        return int(row["schema_version"]) if row is not None else None
    except Exception:  # noqa: BLE001 — schema_meta may not exist on edge DBs
        return None
