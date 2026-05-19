"""MCP tool: list_collections (v0.2.4 C5).

Zotero organises items into user-defined collections (folders).
A Claude session asks 'what's in my Caste Studies collection?' or
'which collections exist in this corpus?' and gets a structured
answer here. Pairs with the upcoming collection-filter on
semantic_search.

Returns the corpus's collections with their parent_key (for nested
trees) and item_count.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

from partial_recall.store.vector_store import VectorStore

LIST_COLLECTIONS_TOOL: Tool = Tool(
    name="list_collections",
    description=(
        "List the user's collections (Zotero folders) for a corpus, "
        "with parent_key for nested trees and item_count per "
        "collection. Use this before semantic_search to discover "
        "available scoping filters."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "corpus": {
                "type": "string",
                "description": (
                    "Corpus to list collections for "
                    "(e.g. 'zotero'). Defaults to 'zotero'."
                ),
                "default": "zotero",
            },
        },
        "additionalProperties": False,
    },
)


async def handle_list_collections(
    arguments: dict[str, Any],
    *,
    store: VectorStore,
) -> list[TextContent]:
    args = arguments or {}
    corpus = args.get("corpus") or "zotero"
    try:
        collections = store.list_collections_for_corpus(corpus)
    except Exception as e:  # noqa: BLE001 — surface, don't crash
        return [TextContent(
            type="text",
            text=json.dumps(
                {"error": f"Could not list collections: {e}",
                 "hint": "Re-index after upgrading partial-recall so "
                         "the collections table is populated."},
                indent=2,
            ),
        )]

    payload = {
        "corpus": corpus,
        "collection_count": len(collections),
        "collections": collections,
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]
