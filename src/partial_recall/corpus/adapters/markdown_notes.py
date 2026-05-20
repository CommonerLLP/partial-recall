"""MarkdownNotesAdapter — index a folder of plain-text markdown notes (v0.3.0).

Markdown is a lightweight writing format: plain text files where
formatting is expressed with simple symbols (# for headings, ** for
bold, [[links]] for cross-references). Most note-taking apps aimed at
researchers and writers store their files this way — including Obsidian,
The Archive, Zettlr, Logseq, nvAlt, and Bear (on export). If your
notes are `.md` files in a folder, this adapter indexes them.

Treats every `.md` file in the configured folder as an indexable item.
Respects:
  - `.obsidian/` subdirectory exclusion (app config, not notes)
  - User-defined `.partial-recallignore` at the notes root
  - YAML frontmatter: extracts title, date, aliases, tags if present
  - Wikilinks `[[note]]` and embeds `![[image]]` are preserved as-is
    in the extracted text so cross-references survive semantic search

Item identity: SHA-256 of the absolute path, so item keys are stable
as long as the file path within the notes folder does not change.

Text extraction: strips the YAML frontmatter block (the `---` section
at the top of many notes) before indexing so the embedder sees prose,
not metadata. Frontmatter values (title, date, tags) are stored as
item metadata.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from partial_recall.corpus.adapters._shared import matches_any, read_ignorefile, stable_item_key
from partial_recall.corpus.types import Item, ItemKind, Source
from partial_recall.errors import CorpusUnavailableError, PartialRecallError

log = structlog.get_logger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class MarkdownNotesAdapterError(PartialRecallError):
    """MarkdownNotesAdapter-specific failure."""



def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body_without_frontmatter).

    Uses a minimal YAML parser (no PyYAML dep) that handles the common
    Obsidian frontmatter patterns: string scalars, lists, dates.
    Falls back to empty dict on anything unusual.
    """
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    body = raw[m.end():]
    fm_raw = m.group(1)
    fm: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None
    for line in fm_raw.splitlines():
        # List continuation
        list_item = re.match(r"^\s+-\s+(.*)", line)
        if list_item and current_key and current_list is not None:
            current_list.append(list_item.group(1).strip().strip('"\''))
            continue
        # Key: value
        kv = re.match(r"^(\w[\w\s-]*):\s*(.*)", line)
        if kv:
            if current_key and current_list is not None:
                fm[current_key] = current_list
            current_list = None
            key = kv.group(1).strip().lower()
            val = kv.group(2).strip().strip('"\'')
            if val == "":
                current_key = key
                current_list = []
            elif val.startswith("[") and val.endswith("]"):
                items = [v.strip().strip('"\'') for v in val[1:-1].split(",") if v.strip()]
                fm[key] = items
                current_key = None
            else:
                fm[key] = val
                current_key = None
        else:
            current_key = None
            current_list = None
    if current_key and current_list is not None:
        fm[current_key] = current_list
    return fm, body


class MarkdownNotesAdapter:
    """Read-only corpus adapter for a folder of markdown notes."""

    name = "markdown_notes"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.NOTE, ItemKind.METADATA})

    def __init__(self, *, notes_path: Path) -> None:
        self.notes_path = Path(notes_path).resolve()
        if not self.notes_path.exists():
            raise CorpusUnavailableError(
                f"Markdown notes folder not found: {self.notes_path}"
            )
        if not self.notes_path.is_dir():
            raise CorpusUnavailableError(
                f"Markdown notes path is not a directory: {self.notes_path}"
            )
        self._ignore_patterns = read_ignorefile(
            self.notes_path / ".partial-recallignore"
        )

    def close(self) -> None:
        return None

    # ------------------------------------------------------------------
    # CorpusAdapter Protocol
    # ------------------------------------------------------------------

    def count_items(self, since: datetime | None = None) -> int | None:
        return sum(1 for _ in self._walk())

    def list_items(self, since: datetime | None = None) -> Iterator[Item]:
        for path in self._walk():
            try:
                stat = path.stat()
            except OSError as e:
                log.warning("markdown_notes.adapter.stat_failed", path=str(path), error=str(e))
                continue
            mtime_dt = datetime.fromtimestamp(stat.st_mtime)
            if since and mtime_dt < since:
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log.warning("markdown_notes.adapter.read_failed", path=str(path), error=str(e))
                continue
            fm, _ = _parse_frontmatter(raw)
            title = fm.get("title") or path.stem
            date_raw = fm.get("date") or fm.get("created") or mtime_dt.isoformat(timespec="seconds")
            tags = fm.get("tags") or fm.get("tag") or []
            if isinstance(tags, str):
                tags = [tags]
            aliases = fm.get("aliases") or fm.get("alias") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            metadata_hash = hashlib.sha256(
                f"{path.resolve()}|{stat.st_mtime}|{stat.st_size}".encode()
            ).hexdigest()
            yield Item(
                item_key=stable_item_key(path),
                corpus="markdown_notes",
                item_type="note",
                title=title,
                date=str(date_raw),
                creators=[],
                abstract=None,
                metadata_hash=metadata_hash,
                corpus_ref=str(path.resolve()),
            )

    def get_sources(self, item: Item) -> Iterator[Source]:
        if not item.corpus_ref:
            return
        yield Source(
            source_type="note",
            source_ref=item.corpus_ref,
            kind=ItemKind.NOTE,
        )

    def get_text(self, item: Item, source: Source) -> str | None:
        if source.source_type != "note" or not source.source_ref:
            return None
        path = Path(source.source_ref)
        if not path.exists():
            log.warning("markdown_notes.adapter.missing_file", path=str(path))
            return None
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log.warning("markdown_notes.adapter.read_failed", path=str(path), error=str(e))
            return None
        _, body = _parse_frontmatter(raw)
        return body.strip() or None

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None  # v0.4.0+

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _walk(self) -> Iterator[Path]:
        for p in self.notes_path.rglob("*.md"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(self.notes_path)
            except ValueError:
                continue
            rel_posix = rel.as_posix()
            # Always exclude Obsidian config directory
            if rel_posix.startswith(".obsidian/") or "/.obsidian/" in rel_posix:
                continue
            # Exclude dotfiles / dot-directories
            if any(part.startswith(".") for part in rel.parts):
                continue
            if matches_any(rel_posix, self._ignore_patterns):
                continue
            yield p
