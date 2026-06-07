"""Registry and loader for CorpusAdapter implementations."""

from __future__ import annotations

import importlib
from collections.abc import Callable

from partial_recall.config.models import PartialRecallConfig
from partial_recall.corpus.adapters.calibre import CalibreAdapter
from partial_recall.corpus.adapters.folder import FolderAdapter
from partial_recall.corpus.adapters.jabref import JabRefAdapter
from partial_recall.corpus.adapters.markdown_notes import MarkdownNotesAdapter
from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.corpus.protocol import CorpusAdapter
from partial_recall.errors import (
    CorpusUnavailableError,
    PartialRecallError,
)

AdapterFactory = Callable[[PartialRecallConfig], CorpusAdapter]


def _zotero_adapter(cfg: PartialRecallConfig) -> CorpusAdapter:
    if not cfg.zotero.enabled:
        raise PartialRecallError(
            "Zotero source is disabled in config. "
            "Set [zotero] enabled = true and re-run."
        )
    if not cfg.zotero.sqlite_path.exists():
        raise CorpusUnavailableError(
            f"Zotero DB not found at {cfg.zotero.sqlite_path}. "
            "Check your config or re-run `partial-recall init`."
        )
    return ZoteroAdapter(
        sqlite_path=cfg.zotero.sqlite_path,
        storage_path=cfg.zotero.storage_path,
    )


def _folder_adapter(cfg: PartialRecallConfig) -> CorpusAdapter:
    if not cfg.folder.enabled:
        raise PartialRecallError(
            "Folder source is disabled in config. "
            "Set [folder] enabled = true and configure [folder] paths = [...]."
        )
    if not cfg.folder.paths:
        raise PartialRecallError(
            "Folder source has no paths configured. "
            "Set [folder] paths = ['/path/to/your/library/']."
        )
    return FolderAdapter(
        roots=cfg.folder.paths,
        recursive=cfg.folder.recursive,
        extensions=frozenset(ext.lower() for ext in cfg.folder.extensions),
    )


def _markdown_notes_adapter(cfg: PartialRecallConfig) -> CorpusAdapter:
    if not cfg.markdown_notes.enabled:
        raise PartialRecallError(
            "Markdown notes source is disabled in config. "
            "Set [markdown_notes] enabled = true and notes_path = '/path/to/your/notes'."
        )
    if not cfg.markdown_notes.notes_path:
        raise PartialRecallError(
            "Markdown notes path not configured. "
            "Set [markdown_notes] notes_path = '/path/to/your/notes'."
        )
    return MarkdownNotesAdapter(notes_path=cfg.markdown_notes.notes_path)


def _jabref_adapter(cfg: PartialRecallConfig) -> CorpusAdapter:
    if not cfg.jabref.enabled:
        raise PartialRecallError(
            "JabRef source is disabled in config. "
            "Set [jabref] enabled = true and bib_path = '/path/to/library.bib'."
        )
    if not cfg.jabref.bib_path:
        raise PartialRecallError(
            "JabRef bib_path not configured. "
            "Set [jabref] bib_path = '/path/to/your/library.bib'."
        )
    return JabRefAdapter(bib_path=cfg.jabref.bib_path)


def _calibre_adapter(cfg: PartialRecallConfig) -> CorpusAdapter:
    if not cfg.calibre.enabled:
        raise PartialRecallError(
            "Calibre source is disabled in config. "
            "Set [calibre] enabled = true and library_path = '/path/to/Calibre Library'."
        )
    if not cfg.calibre.library_path:
        raise PartialRecallError(
            "Calibre library_path not configured. "
            "Set [calibre] library_path = '/path/to/your/Calibre Library'."
        )
    return CalibreAdapter(library_path=cfg.calibre.library_path)


_BUILTIN_FACTORIES: dict[str, AdapterFactory] = {
    "zotero": _zotero_adapter,
    "folder": _folder_adapter,
    "markdown_notes": _markdown_notes_adapter,
    "jabref": _jabref_adapter,
    "calibre": _calibre_adapter,
}

BUILTIN_ADAPTER_NAMES = tuple(_BUILTIN_FACTORIES)


def create_adapter(source: str, cfg: PartialRecallConfig) -> CorpusAdapter:
    """Create a CorpusAdapter from a built-in name or dotted import path."""
    source = source.strip()
    if source in _BUILTIN_FACTORIES:
        return _BUILTIN_FACTORIES[source](cfg)
    if ":" in source:
        return _create_external_adapter(source)
    supported = ", ".join(repr(name) for name in BUILTIN_ADAPTER_NAMES)
    raise PartialRecallError(
        f"Source {source!r} not supported. "
        f"Use {supported}, or a dotted adapter path like "
        "'package.module:AdapterClass'."
    )


def _create_external_adapter(spec: str) -> CorpusAdapter:
    module_name, sep, class_name = spec.partition(":")
    if sep != ":" or not module_name or not class_name:
        raise PartialRecallError(
            f"Adapter path {spec!r} is invalid. "
            "Use dotted import path syntax: 'package.module:AdapterClass'."
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise PartialRecallError(
            f"Could not import adapter module {module_name!r} from {spec!r}: {e}"
        ) from e
    try:
        adapter_cls = getattr(module, class_name)
    except AttributeError as e:
        raise PartialRecallError(
            f"Adapter class {class_name!r} not found in module {module_name!r}."
        ) from e
    try:
        adapter = adapter_cls()
    except PartialRecallError:
        raise
    except TypeError as e:
        raise PartialRecallError(
            f"External adapter {spec!r} could not be constructed with no arguments: {e}"
        ) from e
    except Exception as e:
        raise PartialRecallError(
            f"External adapter {spec!r} failed during construction: {e}"
        ) from e
    if not isinstance(adapter, CorpusAdapter):
        raise PartialRecallError(
            f"External adapter {spec!r} does not satisfy the CorpusAdapter protocol."
        )
    return adapter
