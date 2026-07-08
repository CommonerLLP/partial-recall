"""CorpusAdapter Protocol."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from partial_recall.corpus.types import Item, ItemKind, Source


@runtime_checkable
class CorpusAdapter(Protocol):
    """Pluggable source of indexable items.

    v0.0.1: ZoteroAdapter only.
    v0.1.0: + FolderAdapter.

    Optional hook (NOT part of this protocol, discovered by duck-typing
    so existing adapters keep validating): `migrate_source_refs(store)`.
    If present, run_indexing calls it before walking items; adapters use
    it to rewrite legacy source_ref formats in place so old rows keep
    matching instead of being re-created and re-embedded.
    """

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def capabilities(self) -> set[ItemKind]: ...

    def list_items(self, since: datetime | None = None) -> Iterator[Item]: ...

    def count_items(self, since: datetime | None = None) -> int | None:
        """Total items list_items() will yield, or None if unknown.

        Used by progress UIs to show a determinate bar. Adapters whose
        count is cheap (e.g. SQL COUNT(*)) should implement; adapters
        where counting is as expensive as iterating may return None.
        """
        return None  # default: unknown

    def get_sources(self, item: Item) -> Iterator[Source]: ...

    def get_text(self, item: Item, source: Source) -> str | None: ...

    def get_image(self, item: Item, source: Source) -> bytes | None: ...

    def close(self) -> None: ...
