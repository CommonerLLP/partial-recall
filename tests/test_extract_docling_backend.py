"""The docling PDF backend is optional, lazy, and selected by config (REQ-0034).

Docling recovers layout, reading order, and table structure, which the
PyMuPDF block reader cannot. It is an optional extra because it pulls torch,
torchvision, and opencv, and pins an older transformers than
sentence-transformers wants.

Nothing here installs docling. The tests inject a stub module, which is also
the point: the import must stay lazy, so a default install never pays for it.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.extract import docling_pdf, pdf
from partial_recall.extract.pdf import (
    PdfExtractionError,
    extract_pdf_text,
    get_pdf_backend,
    set_pdf_backend,
)

MARKDOWN = "# Annual Report\n\n| District | Libraries |\n|---|---|\n| Patna | 12 |"


@pytest.fixture(autouse=True)
def restore_backend() -> Iterator[None]:
    """The backend is process state. Never leak it between tests."""
    previous = get_pdf_backend()
    docling_pdf._converter.cache_clear()
    yield
    set_pdf_backend(previous)
    docling_pdf._converter.cache_clear()


@pytest.fixture
def fake_docling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a stub `docling.document_converter` in sys.modules."""

    class _Doc:
        def export_to_markdown(self) -> str:
            return MARKDOWN

    class _Result:
        document = _Doc()

    class DocumentConverter:
        def convert(self, source: str) -> _Result:
            return _Result()

    pkg = types.ModuleType("docling")
    mod = types.ModuleType("docling.document_converter")
    mod.DocumentConverter = DocumentConverter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docling", pkg)
    monkeypatch.setitem(sys.modules, "docling.document_converter", mod)


def test_default_backend_is_pymupdf() -> None:
    assert get_pdf_backend() == "pymupdf"


def test_set_pdf_backend_rejects_an_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown pdf backend"):
        set_pdf_backend("tesseract")


def test_docling_backend_returns_structured_markdown(
    fake_docling: None, tmp_path: Path
) -> None:
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4 not really a pdf")
    set_pdf_backend("docling")
    assert extract_pdf_text(target) == MARKDOWN


def test_a_table_survives_as_a_table(fake_docling: None, tmp_path: Path) -> None:
    """The reason the backend exists. A block reader loses the row grouping."""
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4 not really a pdf")
    set_pdf_backend("docling")
    text = extract_pdf_text(target)
    assert "| District | Libraries |" in text
    assert "| Patna | 12 |" in text


def test_missing_docling_raises_with_an_install_hint(tmp_path: Path) -> None:
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4 not really a pdf")
    set_pdf_backend("docling")
    if docling_pdf.docling_available():
        pytest.skip("docling is installed in this environment")
    with pytest.raises(PdfExtractionError, match=r"partial-recall\[docling\]"):
        extract_pdf_text(target)


def test_a_missing_file_raises_before_docling_loads(tmp_path: Path) -> None:
    set_pdf_backend("docling")
    with pytest.raises(PdfExtractionError, match="PDF not found"):
        extract_pdf_text(tmp_path / "absent.pdf")


def test_the_import_stays_lazy() -> None:
    """A default install must never pay for the docling dependency."""
    import ast

    for module in (pdf, docling_pdf):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in tree.body:  # module level only, not function bodies
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.split(".")[0] == "docling" for n in names), (
                f"{module.__name__} imports docling at module level"
            )


def test_load_config_applies_the_configured_backend(tmp_path: Path) -> None:
    """Round-trip through save_config so Windows paths stay TOML-safe."""
    from partial_recall.config.loader import load_config, save_config
    from partial_recall.config.models import (
        IndexConfig,
        PartialRecallConfig,
        ZoteroConfig,
    )

    cfg_path = tmp_path / "config.toml"
    save_config(
        PartialRecallConfig(
            index=IndexConfig(
                vector_db_path=tmp_path / "vectors.sqlite", pdf_backend="docling"
            ),
            zotero=ZoteroConfig(
                sqlite_path=tmp_path / "zotero.sqlite",
                storage_path=tmp_path / "storage",
            ),
        ),
        cfg_path,
    )
    cfg = load_config(cfg_path)
    assert cfg.index.pdf_backend == "docling"
    assert get_pdf_backend() == "docling"
