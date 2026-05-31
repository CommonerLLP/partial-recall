"""MCP tool: place_item.

Position a candidate work (title + optional blurb, metadata only)
against the existing corpus: nearest neighbours, a density signal
(dense neighbourhood vs a gap), and a likely-owned flag. This is the
discovery feature's headline — "here is where this new book falls in
what I already know" — and it is READ-ONLY.

Returns a single TextContent with structured JSON, or a structured
error payload (never an exception) so the MCP loop survives.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

from partial_recall.discovery.positioning import (
    DENSE_TOP,
    LIKELY_OWNED_THRESHOLD,
    MODERATE_TOP,
    Neighbour,
    position,
)
from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.errors import PartialRecallError
from partial_recall.store.vector_store import VectorStore

PLACE_ITEM_TOOL: Tool = Tool(
    name="place_item",
    description=(
        "Position a candidate work against the user's existing corpus. "
        "Given a book/article title (and optional blurb or abstract), "
        "returns the nearest neighbours among what the user has already "
        "read, a density signal (a dense neighbourhood means the topic is "
        "well-read; a thin/empty one means the work opens a gap), and a "
        "likely-owned flag when a near-identical text is already indexed. "
        "Use this to place newly discovered or forthcoming books on the "
        "user's reading map. Read-only."
    ),
    inputSchema={
        "type": "object",
        "required": ["title"],
        "properties": {
            "title": {
                "type": "string",
                "description": "Title of the candidate work (with subtitle if any).",
            },
            "blurb": {
                "type": "string",
                "description": (
                    "Optional abstract, jacket blurb, or description. "
                    "Improves positioning accuracy."
                ),
            },
            "top_k": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 50,
                "description": "How many nearest neighbours to return.",
            },
            "corpus": {
                "type": "string",
                "description": (
                    "Optional: restrict the neighbourhood to one corpus "
                    "(e.g. 'zotero'). Omit to position against everything."
                ),
                "enum": ["zotero", "folder", "markdown_notes", "jabref", "calibre"],
            },
        },
        "additionalProperties": False,
    },
)


def _error(message: str, hint: str) -> TextContent:
    return TextContent(
        type="text",
        text=json.dumps({"error": message, "hint": hint}, indent=2),
    )


def _serialise_neighbour(n: Neighbour) -> dict[str, Any]:
    return {
        "score": round(n.score, 4),
        "item_key": n.item_key,
        "corpus": n.corpus,
        "title": n.title,
        "creators": n.creators,
        "date": n.date,
        "source_type": n.source_type,
        "preview": n.preview,
    }


async def handle_place_item(
    arguments: dict[str, Any],
    *,
    store: VectorStore,
    provider: EmbeddingProvider,
) -> list[TextContent]:
    args = arguments or {}
    title = args.get("title")
    if not title or not isinstance(title, str):
        return [_error(
            "Missing or invalid 'title' (must be a non-empty string).",
            "Provide the work's title as 'title'.",
        )]

    blurb = args.get("blurb")
    if blurb is not None and not isinstance(blurb, str):
        blurb = None

    top_k_raw = args.get("top_k", 10)
    try:
        top_k = int(top_k_raw)
    except (TypeError, ValueError):
        top_k = 10
    top_k = max(1, min(50, top_k))

    corpus = args.get("corpus")

    try:
        placement = position(
            store=store, provider=provider, title=title, blurb=blurb,
            top_k=top_k, corpus=corpus,
        )
    except PartialRecallError as exc:
        return [_error(
            str(exc) or exc.__class__.__name__,
            exc.actionable_hint or "See partial-recall logs for details.",
        )]
    except Exception as exc:  # defensive: never crash the MCP loop
        return [_error(
            f"{exc.__class__.__name__}: {exc}",
            "Unexpected error; see partial-recall logs.",
        )]

    active = store.get_active_run()
    payload = {
        "query_text": placement.query_text,
        "placement": {
            "density": placement.density,
            "top_score": (
                round(placement.top_score, 4)
                if placement.top_score is not None else None
            ),
            "mean_score": (
                round(placement.mean_score, 4)
                if placement.mean_score is not None else None
            ),
            "related_count": placement.related_count,
            "likely_owned": placement.likely_owned,
            "owned_match": (
                _serialise_neighbour(placement.owned_match)
                if placement.owned_match else None
            ),
        },
        "neighbours": [_serialise_neighbour(n) for n in placement.neighbours],
        "interpretation": {
            "note": (
                "Density and likely_owned are heuristic and relative to the "
                "active embedding model. Trust the raw scores over the labels."
            ),
            "thresholds": {
                "likely_owned": LIKELY_OWNED_THRESHOLD,
                "dense_top": DENSE_TOP,
                "moderate_top": MODERATE_TOP,
            },
            "embedding_model": active.model_name if active else None,
            "embedding_provider": active.provider if active else None,
            "active_run_id": active.run_id if active else None,
        },
    }
    return [TextContent(
        type="text",
        text=json.dumps(payload, indent=2, ensure_ascii=False),
    )]
