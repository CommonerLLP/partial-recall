"""MCP tool: fetch_item.

Given a Zotero parent item_key, resolve the child attachment key, fetch 
the PDF (or its extracted text), and return structured JSON.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

from partial_recall.config.models import PartialRecallConfig
from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.corpus.zotero_fetch import fetch_zotero_attachment
from partial_recall.paths import download_cache_dir

FETCH_ITEM_TOOL: Tool = Tool(
    name="fetch_item",
    description=(
        "Fetch an attachment file (like a PDF) or its extracted text for a given "
        "parent item in the corpus. Currently only supports 'zotero' corpus. "
        "It resolves the parent item key to an attachment key, checks local storage, "
        "and falls back to the Zotero Web API if needed."
    ),
    inputSchema={
        "type": "object",
        "required": ["item_key"],
        "properties": {
            "item_key": {
                "type": "string",
                "description": "The parent item key (e.g. 28H8BQST).",
            },
            "corpus": {
                "type": "string",
                "description": "The corpus to fetch from. Currently only 'zotero' is supported.",
                "enum": ["zotero"],
                "default": "zotero",
            },
            "text_mode": {
                "type": "boolean",
                "description": "Extract and return reading-order text from the PDF.",
                "default": False,
            },
            "download_missing": {
                "type": "boolean",
                "description": "Whether to fallback to the Web API if the attachment is missing locally.",
                "default": True,
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


async def handle_fetch_item(
    arguments: dict[str, Any],
    *,
    config: PartialRecallConfig,
) -> list[TextContent]:
    args = arguments or {}
    item_key = args.get("item_key")
    if not item_key or not isinstance(item_key, str):
        return [_error(
            "Missing or invalid 'item_key' (must be a non-empty string).",
            "Provide the parent item's key as 'item_key'.",
        )]

    corpus = args.get("corpus", "zotero")
    if corpus != "zotero":
        return [_error(
            f"Unsupported corpus '{corpus}'. Only 'zotero' is supported.",
            "Use corpus='zotero'.",
        )]

    if not config.zotero.enabled:
        return [_error("Zotero is disabled in config.", "Enable Zotero in config.toml.")]

    text_mode = bool(args.get("text_mode", False))
    download_missing = bool(args.get("download_missing", True))

    adapter = ZoteroAdapter(
        sqlite_path=config.zotero.sqlite_path,
        storage_path=config.zotero.storage_path,
    )
    
    cache_dir = download_cache_dir() / "zotero"

    try:
        res = fetch_zotero_attachment(
            item_key=item_key,
            adapter=adapter,
            config=config.zotero,
            cache_dir=cache_dir,
            download_missing=download_missing,
            extract_text=text_mode,
        )
    except Exception as exc:
        return [_error(str(exc), "Failed to fetch attachment.")]
    finally:
        adapter.close()

    if not res.attachment_key:
        return [_error(f"No PDF attachments found for item '{item_key}'.", "Check the item key.")]

    payload = {
        "item_key": res.item_key,
        "attachment_key": res.attachment_key,
        "path": str(res.path.absolute()) if res.path else None,
        "content_type": res.content_type,
        "source": res.source,
    }
    if text_mode:
        payload["text"] = res.text

    return [TextContent(
        type="text",
        text=json.dumps(payload, indent=2, ensure_ascii=False),
    )]
