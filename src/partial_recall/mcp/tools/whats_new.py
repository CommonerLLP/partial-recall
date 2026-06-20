"""MCP tool: whats_new — new academic releases, routed by query axis.

Answers questions like "has Duke published anything on caste?", "what's new in
South Asian studies?", or "new on West Bengal in 2024?" by routing to the source
that owns the axis (find_books):

  field / discipline / studies   -> New Books Network channel
  press x subject                -> OpenLibrary
  topic + place + year (+ CIP)   -> Library of Congress (LCSH/LCC)

Pure catalog metadata — no embeddings, no API keys. Read-only.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from mcp.types import TextContent, Tool

from partial_recall.discovery.releases import find_books

WHATS_NEW_TOOL: Tool = Tool(
    name="whats_new",
    description=(
        "Find newly published/catalogued academic books, routed to the right "
        "source by what you ask. Axes: `field` (a discipline/'studies' — e.g. "
        "'South Asian Studies' — via New Books Network channels); `press` × "
        "`subject` (e.g. did Duke publish on caste — via OpenLibrary); "
        "`subject`/`place`/`year` (e.g. new on West Bengal in 2024, incl. "
        "forthcoming CIP — via the Library of Congress). Keep subjects specific "
        "(LCSH-style). `press` also filters results from any source. Returns "
        "title, authors, publisher, year, LCSH/LCC/LCCN, and a CIP flag."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "field": {"type": "string",
                      "description": "Discipline/studies field, e.g. 'South Asian Studies'."},
            "press": {"type": "string",
                      "description": "Press short name (e.g. 'chicago', 'stanford', 'duke')."},
            "subject": {"type": "array", "items": {"type": "string"},
                        "description": 'LCSH subject term(s), e.g. ["West Bengal"] or ["Caste"].'},
            "place": {"type": "string", "description": "Geographic subject, e.g. 'West Bengal'."},
            "year": {"type": "string", "description": "Exact publication year, e.g. '2024'."},
            "since": {"type": "string",
                      "description": "For a `field` query: only NBN episodes aired on/after "
                                     "this date (YYYY-MM-DD), e.g. '2026-01-01'."},
        },
        "additionalProperties": False,
    },
)


async def handle_whats_new(arguments: dict[str, Any], **_ignored: Any) -> list[TextContent]:
    args = arguments or {}
    if not any(args.get(k) for k in ("field", "press", "subject", "place", "year")):
        return [TextContent(type="text", text=json.dumps(
            {"error": "Give at least one of: field, press, subject, place, year.",
             "hint": 'e.g. {"press":"duke","subject":["Caste"]} or '
                     '{"subject":["West Bengal"],"year":"2024"} or '
                     '{"field":"South Asian Studies","since":"2026-01-01"}'},
            indent=2))]
    try:
        res = find_books(
            field=args.get("field"), press=args.get("press"),
            subject=args.get("subject"), place=args.get("place"),
            year=args.get("year"), since=args.get("since"))
    except Exception as exc:  # noqa: BLE001 — never crash the MCP loop
        return [TextContent(type="text", text=json.dumps(
            {"error": f"{exc.__class__.__name__}: {exc}",
             "hint": "Try a narrower subject; LoC throttles broad queries."}, indent=2))]

    payload = {
        "sources": res["sources"],
        "count": len(res["results"]),
        "results": [asdict(r) for r in res["results"]],
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2, ensure_ascii=False))]
