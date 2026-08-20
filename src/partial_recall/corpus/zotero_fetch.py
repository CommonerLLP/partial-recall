from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from partial_recall.config.models import ZoteroConfig
from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.extract.docx import extract_docx_text
from partial_recall.extract.epub import extract_epub_text
from partial_recall.extract.pdf import extract_pdf_text

# Attachment content types this module can fetch, in preference order.
# A PDF wins when an item carries more than one, because annotations and
# page numbers only exist on the PDF.
_FETCHABLE = (
    ("application/pdf", ".pdf"),
    ("application/epub+zip", ".epub"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
)
_EXTRACTORS = {
    ".pdf": extract_pdf_text,
    ".epub": extract_epub_text,
    ".docx": extract_docx_text,
}


def _extract(path: Path) -> str | None:
    extractor = _EXTRACTORS.get(path.suffix.lower())
    return extractor(path) if extractor else None


@dataclass
class FetchResult:
    item_key: str
    attachment_key: str | None
    path: Path | None
    text: str | None
    source: str | None  # "local" | "web"
    content_type: str | None


def fetch_zotero_attachment(
    item_key: str,
    adapter: ZoteroAdapter,
    config: ZoteroConfig,
    cache_dir: Path,
    download_missing: bool = True,
    extract_text: bool = False,
) -> FetchResult:
    """Fetch the source file for a given item key, resolving the attachment."""

    # 1. Parent resolution
    row = adapter._conn.execute(
        """
        SELECT itemID
        FROM items
        WHERE key = ?
          AND itemID NOT IN (SELECT itemID FROM deletedItems)
        """,
        (item_key,),
    ).fetchone()

    if not row:
        raise ValueError(f"Item '{item_key}' not found in local Zotero DB or is deleted.")

    parent_id = row["itemID"]

    # 2. Get attachments. A PDF wins when the item carries more than one.
    placeholders = ",".join("?" * len(_FETCHABLE))
    att_rows = adapter._conn.execute(f"""
        SELECT a.itemID, a.path, a.linkMode, a.contentType, child.key as att_key, child.libraryID
        FROM itemAttachments a
        JOIN items child ON child.itemID = a.itemID
        WHERE a.parentItemID = ?
          AND a.contentType IN ({placeholders})
          AND child.itemID NOT IN (SELECT itemID FROM deletedItems)
    """, (parent_id, *(ct for ct, _ in _FETCHABLE))).fetchall()

    if not att_rows:
        return FetchResult(item_key, None, None, None, None, None)

    order = {ct: i for i, (ct, _) in enumerate(_FETCHABLE)}
    att_rows.sort(key=lambda r: order.get((r["contentType"] or "").lower(), len(order)))
    att = att_rows[0]
    att_key = att["att_key"]
    content_type = att["contentType"]
    link_mode = att["linkMode"]
    path_val = att["path"] or ""
    library_id = att["libraryID"]

    # 3. Check local first
    # Zotero linkMode:
    # 0 = imported_url, 1 = imported_file, 2 = linked_file, 3 = linked_uri
    if link_mode == 2 and path_val.startswith("attachments:"):
        # linked file relative to Zotero's Base Attachment Directory
        # Zotero doesn't store the base attachment directory in sqlite in a simple way
        # it might be in prefs.js. For now, we return absolute if it's absolute, else error.
        pass

    suffix = dict(_FETCHABLE).get((content_type or "").lower(), ".pdf")

    local_dir = adapter.storage_path / att_key
    if local_dir.exists():
        for f in local_dir.iterdir():
            if f.suffix.lower() == suffix:
                text = _extract(f) if extract_text else None
                return FetchResult(item_key, att_key, f, text, "local", content_type)

    # 4. Fallback to Web API
    if not download_missing:
        return FetchResult(item_key, att_key, None, None, None, content_type)

    api_key = config.api_key or os.environ.get("ZOTERO_API_KEY")
    user_id = config.user_id or os.environ.get("ZOTERO_USER_ID")
    group_id = config.group_id or os.environ.get("ZOTERO_GROUP_ID")

    if not api_key:
        raise ValueError(
            "Attachment not found locally and ZOTERO_API_KEY not provided "
            "for Web API fallback"
        )

    # Determine URL
    # In Zotero, libraryID 1 is usually the user library.
    # We could guess based on libraryID or just try group if group_id is provided.
    # Let's check group_id first if libraryID != 1.
    if library_id != 1 and group_id:
        url = f"https://api.zotero.org/groups/{group_id}/items/{att_key}/file"
    elif user_id:
        url = f"https://api.zotero.org/users/{user_id}/items/{att_key}/file"
    else:
        raise ValueError(
            "Attachment not found locally and ZOTERO_USER_ID or "
            "ZOTERO_GROUP_ID not provided"
        )

    req = urllib.request.Request(url, headers={"Zotero-API-Key": api_key})

    filename = f"attachment{suffix}"
    if path_val.startswith("storage:"):
        filename = path_val.split(":", 1)[1]

    cache_file = cache_dir / att_key / filename
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with urllib.request.urlopen(req) as resp, open(cache_file, "wb") as out:
            out.write(resp.read())
    except urllib.error.HTTPError as e:
        raise ValueError(f"Failed to fetch attachment from Zotero API: HTTP {e.code}") from e

    text = _extract(cache_file) if extract_text else None
    return FetchResult(item_key, att_key, cache_file, text, "web", content_type)
