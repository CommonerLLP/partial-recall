"""MCP tool: library_search.

Structured metadata search over the Zotero library — title/abstract
free-text, creator last-name filter, tag filter, collection filter,
item-type filter, year range, dateAdded range, and sort order.

Queries Zotero's own SQLite in read-only mode. Does NOT touch the
partial-recall vector DB; this is purely a metadata layer.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

LIBRARY_SEARCH_TOOL: Tool = Tool(
    name="library_search",
    description=(
        "Search the user's Zotero library by structured metadata: "
        "author, tag, collection, year range, item type, or free-text "
        "title/abstract match. Complements semantic_search for SQL-shaped "
        "scholarly queries."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Free-text match against title and abstract. "
                    "Case-insensitive substring match."
                ),
            },
            "creators": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Match items where ANY listed last name appears in creators. "
                    "Case-insensitive."
                ),
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Match items carrying ALL listed tags. "
                    "Case-insensitive exact match."
                ),
            },
            "collections": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Match items in ANY of these collections "
                    "(matched by collection name, case-insensitive)."
                ),
            },
            "item_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Filter by Zotero item type, e.g. 'journalArticle', "
                    "'book', 'bookSection', 'thesis', 'report'."
                ),
            },
            "year_min": {
                "type": "integer",
                "description": "Include items published in this year or later.",
            },
            "year_max": {
                "type": "integer",
                "description": "Include items published in this year or earlier.",
            },
            "added_after": {
                "type": "string",
                "description": "ISO-8601 date; include items added on or after this date.",
            },
            "added_before": {
                "type": "string",
                "description": "ISO-8601 date; include items added on or before this date.",
            },
            "sort_by": {
                "type": "string",
                "enum": [
                    "year_desc", "year_asc",
                    "title_asc", "title_desc",
                    "added_desc", "added_asc",
                ],
                "default": "year_desc",
                "description": "Sort order for results.",
            },
            "limit": {
                "type": "integer",
                "default": 50,
                "minimum": 1,
                "maximum": 500,
                "description": "Maximum number of items to return.",
            },
        },
    },
)

_SORT_MAP = {
    "year_desc":   "CAST(SUBSTR(date_val, 1, 4) AS INTEGER) DESC NULLS LAST, i.dateAdded DESC",
    "year_asc":    "CAST(SUBSTR(date_val, 1, 4) AS INTEGER) ASC NULLS LAST, i.dateAdded ASC",
    "title_asc":   "LOWER(title_val) ASC NULLS LAST",
    "title_desc":  "LOWER(title_val) DESC NULLS LAST",
    "added_desc":  "i.dateAdded DESC",
    "added_asc":   "i.dateAdded ASC",
}

_YEAR_RE = re.compile(r"^\d{4}")


def _open_zotero_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_creators(conn: sqlite3.Connection, item_ids: list[int]) -> dict[int, list[dict]]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"""
        SELECT ic.itemID, c.firstName, c.lastName
        FROM itemCreators ic
        JOIN creators c ON c.creatorID = ic.creatorID
        WHERE ic.itemID IN ({placeholders})
        ORDER BY ic.itemID, ic.orderIndex
        """,
        item_ids,
    ).fetchall()
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["itemID"], []).append(
            {"first": r["firstName"] or "", "last": r["lastName"] or ""}
        )
    return out


def _fetch_tags(conn: sqlite3.Connection, item_ids: list[int]) -> dict[int, list[str]]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"""
        SELECT it.itemID, t.name
        FROM itemTags it
        JOIN tags t ON t.tagID = it.tagID
        WHERE it.itemID IN ({placeholders})
        ORDER BY it.itemID, t.name
        """,
        item_ids,
    ).fetchall()
    out: dict[int, list[str]] = {}
    for r in rows:
        out.setdefault(r["itemID"], []).append(r["name"])
    return out


def _fetch_collections(conn: sqlite3.Connection, item_ids: list[int]) -> dict[int, list[str]]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"""
        SELECT ci.itemID, c.collectionName
        FROM collectionItems ci
        JOIN collections c ON c.collectionID = ci.collectionID
        WHERE ci.itemID IN ({placeholders})
          AND c.collectionID NOT IN (SELECT collectionID FROM deletedCollections)
        ORDER BY ci.itemID, c.collectionName
        """,
        item_ids,
    ).fetchall()
    out: dict[int, list[str]] = {}
    for r in rows:
        out.setdefault(r["itemID"], []).append(r["collectionName"])
    return out


def _fetch_field(conn: sqlite3.Connection, item_ids: list[int], field_name: str) -> dict[int, str]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"""
        SELECT d.itemID, v.value
        FROM itemData d
        JOIN fields f ON f.fieldID = d.fieldID
        JOIN itemDataValues v ON v.valueID = d.valueID
        WHERE d.itemID IN ({placeholders}) AND f.fieldName = ?
        """,
        [*item_ids, field_name],
    ).fetchall()
    return {r["itemID"]: r["value"] for r in rows}


def _run_library_search(
    conn: sqlite3.Connection,
    *,
    query: str | None,
    creators: list[str],
    tags: list[str],
    collections: list[str],
    item_types: list[str],
    year_min: int | None,
    year_max: int | None,
    added_after: str | None,
    added_before: str | None,
    sort_by: str,
    limit: int,
) -> list[dict[str, Any]]:
    where: list[str] = [
        "i.itemID NOT IN (SELECT itemID FROM deletedItems)",
        "it.typeName NOT IN ('attachment', 'note')",
    ]
    params: list[Any] = []

    # Item type filter
    if item_types:
        ph = ",".join("?" * len(item_types))
        where.append(f"it.typeName IN ({ph})")
        params.extend(item_types)

    # dateAdded range
    if added_after:
        where.append("i.dateAdded >= ?")
        params.append(added_after)
    if added_before:
        where.append("i.dateAdded <= ?")
        params.append(added_before)

    # Creator filter — any of the listed last names
    if creators:
        sub_parts = " OR ".join(["LOWER(c.lastName) = LOWER(?)" for _ in creators])
        where.append(
            f"""i.itemID IN (
                SELECT ic.itemID FROM itemCreators ic
                JOIN creators c ON c.creatorID = ic.creatorID
                WHERE {sub_parts}
            )"""
        )
        params.extend(creators)

    # Tag filter — ALL tags must be present
    for tag in tags:
        where.append(
            """i.itemID IN (
                SELECT it2.itemID FROM itemTags it2
                JOIN tags t2 ON t2.tagID = it2.tagID
                WHERE LOWER(t2.name) = LOWER(?)
            )"""
        )
        params.append(tag)

    # Collection filter — any of the listed collection names
    if collections:
        sub_parts = " OR ".join(["LOWER(c2.collectionName) = LOWER(?)" for _ in collections])
        where.append(
            f"""i.itemID IN (
                SELECT ci.itemID FROM collectionItems ci
                JOIN collections c2 ON c2.collectionID = ci.collectionID
                WHERE {sub_parts}
            )"""
        )
        params.extend(collections)

    # Free-text filter against title + abstract
    if query:
        where.append(
            """(
                i.itemID IN (
                    SELECT d.itemID FROM itemData d
                    JOIN fields f ON f.fieldID = d.fieldID
                    JOIN itemDataValues v ON v.valueID = d.valueID
                    WHERE f.fieldName = 'title' AND LOWER(v.value) LIKE LOWER(?)
                )
                OR i.itemID IN (
                    SELECT d.itemID FROM itemData d
                    JOIN fields f ON f.fieldID = d.fieldID
                    JOIN itemDataValues v ON v.valueID = d.valueID
                    WHERE f.fieldName = 'abstractNote' AND LOWER(v.value) LIKE LOWER(?)
                )
            )"""
        )
        like = f"%{query}%"
        params.extend([like, like])

    where_sql = " AND ".join(where)
    order_sql = _SORT_MAP.get(sort_by, _SORT_MAP["year_desc"])

    # Pull itemID, key, typeName, dateAdded plus title/date via subqueries.
    sql = f"""
        SELECT
            i.itemID,
            i.key,
            it.typeName,
            i.dateAdded,
            title_sub.value  AS title_val,
            date_sub.value   AS date_val,
            pub_sub.value    AS publication_val
        FROM items i
        JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
        LEFT JOIN (
            SELECT d.itemID, v.value FROM itemData d
            JOIN fields f ON f.fieldID = d.fieldID
            JOIN itemDataValues v ON v.valueID = d.valueID
            WHERE f.fieldName = 'title'
        ) title_sub ON title_sub.itemID = i.itemID
        LEFT JOIN (
            SELECT d.itemID, v.value FROM itemData d
            JOIN fields f ON f.fieldID = d.fieldID
            JOIN itemDataValues v ON v.valueID = d.valueID
            WHERE f.fieldName = 'date'
        ) date_sub ON date_sub.itemID = i.itemID
        LEFT JOIN (
            SELECT d.itemID, v.value FROM itemData d
            JOIN fields f ON f.fieldID = d.fieldID
            JOIN itemDataValues v ON v.valueID = d.valueID
            WHERE f.fieldName IN ('publicationTitle', 'publisher', 'university')
            LIMIT 1
        ) pub_sub ON pub_sub.itemID = i.itemID
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []

    item_ids = [r["itemID"] for r in rows]
    creators_map = _fetch_creators(conn, item_ids)
    tags_map = _fetch_tags(conn, item_ids)
    collections_map = _fetch_collections(conn, item_ids)

    results = []
    for r in rows:
        iid = r["itemID"]
        date_val = r["date_val"] or ""
        m = _YEAR_RE.match(date_val)
        year = int(m.group()) if m else None

        # Year range filter — applied here because SQLite CAST on a
        # potentially-absent LEFT JOIN column is fragile in WHERE.
        if year_min is not None and (year is None or year < year_min):
            continue
        if year_max is not None and (year is None or year > year_max):
            continue

        results.append({
            "item_key": r["key"],
            "item_type": r["typeName"],
            "title": r["title_val"],
            "creators": creators_map.get(iid, []),
            "year": year,
            "date": date_val or None,
            "publication": r["publication_val"],
            "tags": tags_map.get(iid, []),
            "collections": collections_map.get(iid, []),
            "date_added": r["dateAdded"],
        })

    return results


async def handle_library_search(
    arguments: dict[str, Any],
    *,
    zotero_sqlite_path: Path | None,
) -> list[TextContent]:
    def _err(msg: str, hint: str = "") -> list[TextContent]:
        return [TextContent(
            type="text",
            text=json.dumps({"error": msg, "hint": hint}, indent=2),
        )]

    if zotero_sqlite_path is None:
        return _err(
            "Zotero corpus not configured.",
            "Set [zotero] enabled = true and sqlite_path in config.toml, "
            "then restart the MCP server.",
        )
    if not zotero_sqlite_path.exists():
        return _err(
            f"Zotero DB not found: {zotero_sqlite_path}",
            "Check [zotero] sqlite_path in config.toml.",
        )

    # Parse + validate arguments
    query = arguments.get("query") or None
    creators: list[str] = [str(c) for c in (arguments.get("creators") or [])]
    tags: list[str] = [str(t) for t in (arguments.get("tags") or [])]
    collections: list[str] = [str(c) for c in (arguments.get("collections") or [])]
    item_types: list[str] = [str(t) for t in (arguments.get("item_types") or [])]

    try:
        year_min = int(arguments["year_min"]) if "year_min" in arguments else None
        year_max = int(arguments["year_max"]) if "year_max" in arguments else None
    except (TypeError, ValueError):
        return _err("year_min / year_max must be integers.")

    added_after = arguments.get("added_after") or None
    added_before = arguments.get("added_before") or None

    sort_by = str(arguments.get("sort_by") or "year_desc")
    if sort_by not in _SORT_MAP:
        sort_by = "year_desc"

    try:
        limit = max(1, min(500, int(arguments.get("limit", 50))))
    except (TypeError, ValueError):
        limit = 50

    started = time.perf_counter()
    try:
        conn = _open_zotero_readonly(zotero_sqlite_path)
        try:
            results = _run_library_search(
                conn,
                query=query,
                creators=creators,
                tags=tags,
                collections=collections,
                item_types=item_types,
                year_min=year_min,
                year_max=year_max,
                added_after=added_after,
                added_before=added_before,
                sort_by=sort_by,
                limit=limit,
            )
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        return _err(
            f"Zotero DB error: {exc}",
            "Zotero may be locked; try closing Zotero or retrying.",
        )
    except Exception as exc:
        return _err(f"{exc.__class__.__name__}: {exc}", "Unexpected error; check logs.")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    payload = {
        "results": results,
        "total": len(results),
        "query_metadata": {
            "elapsed_ms": elapsed_ms,
            "filters": {
                k: v for k, v in {
                    "query": query,
                    "creators": creators or None,
                    "tags": tags or None,
                    "collections": collections or None,
                    "item_types": item_types or None,
                    "year_min": year_min,
                    "year_max": year_max,
                    "added_after": added_after,
                    "added_before": added_before,
                    "sort_by": sort_by,
                    "limit": limit,
                }.items() if v is not None
            },
        },
    }
    return [TextContent(type="text", text=json.dumps(payload, indent=2, ensure_ascii=False))]
