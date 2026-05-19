#!/usr/bin/env python3
"""Generate docs/config/reference.md from the Pydantic models.

Reading the Pydantic model classes is the single source of truth for
what options exist; this script walks them and emits a Markdown table
per section. Docs and code stay in sync because the docs ARE the
code's introspection.

Usage:
    python scripts/generate_config_reference.py
        → writes docs/config/reference.md

Idempotent: re-runs produce byte-identical output unless the models
change. Wire into a pre-commit / CI gate if you want docs-drift to
fail the build.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from partial_recall.config.models import (  # noqa: E402
    EmbeddingConfig,
    FolderConfig,
    IndexConfig,
    LoggingConfig,
    ServerConfig,
    ZoteroConfig,
)

# Section order matches what `partial-recall init` writes.
SECTIONS: list[tuple[str, type, str]] = [
    ("embedding", EmbeddingConfig,
     "Which embedding provider produces vectors, which model, batch shape."),
    ("index", IndexConfig,
     "Where the SQLite vector store lives + chunking parameters."),
    ("zotero", ZoteroConfig,
     "Pointer to a Zotero library; how to read it."),
    ("folder", FolderConfig,
     "Optional non-Zotero corpus: a directory tree of documents."),
    ("server", ServerConfig,
     "MCP server transport + auth mode."),
    ("logging", LoggingConfig,
     "Log level + output format."),
]

# Top-level config-schema-version field is on PartialRecallConfig itself.
TOP_LEVEL_FIELD = "config_schema_version"


def _render_default(value: object) -> str:
    """Render a default value in a Markdown-table-friendly form."""
    if value is None:
        return "_unset_"
    if isinstance(value, str):
        return f"`\"{value}\"`"
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    if isinstance(value, (list, tuple)):
        if not value:
            return "`[]`"
        items = ", ".join(f"`{v!r}`" for v in value)
        return f"`[{items}]`"
    return f"`{value!r}`"


def _field_rows(model_cls: type) -> list[tuple[str, str, str, str]]:
    """For each model field, return (name, type, default, description)."""
    from pydantic_core import PydanticUndefined  # type: ignore[import-untyped]
    rows = []
    for name, info in model_cls.model_fields.items():
        # Pydantic v2: info has annotation, default / default_factory, description.
        anno = info.annotation
        type_name = getattr(anno, "__name__", str(anno))
        # Required fields: render as **required** instead of leaking
        # the Pydantic sentinel string into public docs. (Codex P2.)
        if info.is_required():
            default_md = "**required**"
        else:
            try:
                default = info.get_default(call_default_factory=True)
            except Exception:  # noqa: BLE001
                default = None
            if default is PydanticUndefined:
                default_md = "**required**"
            else:
                default_md = _render_default(default)
        desc = info.description or ""
        rows.append((name, type_name, default_md, desc))
    return rows


def _section_md(section_name: str, model_cls: type, prose: str) -> list[str]:
    rows = _field_rows(model_cls)
    lines = [
        f"## `[{section_name}]`",
        "",
        prose,
        "",
        "| field | type | default | description |",
        "|---|---|---|---|",
    ]
    for name, type_name, default_md, desc in rows:
        # Pipe-escape any pipes in descriptions (rare but possible).
        safe_desc = desc.replace("|", "\\|")
        lines.append(
            f"| `{name}` | `{type_name}` | {default_md} | {safe_desc} |"
        )
    lines.append("")
    return lines


def build_reference() -> str:
    lines: list[str] = [
        "# Configuration reference",
        "",
        "Generated from the Pydantic models in "
        "`src/partial_recall/config/models.py` by "
        "`scripts/generate_config_reference.py`. Edit the model field "
        "descriptions, not this file.",
        "",
        "The config lives at the platform's user-config dir "
        "(see `partial-recall doctor` for the path on your system). "
        "It's a TOML file with one `[section]` per Pydantic model.",
        "",
        "## Top-level",
        "",
        "| field | type | default | description |",
        "|---|---|---|---|",
        f"| `{TOP_LEVEL_FIELD}` | `int` | `1` | "
        "Increments when the config-file schema changes in a "
        "backward-incompatible way. v0.2.x = 1. |",
        "",
    ]
    for section_name, model_cls, prose in SECTIONS:
        lines.extend(_section_md(section_name, model_cls, prose))
    return "\n".join(lines)


def main() -> int:
    output_path = REPO_ROOT / "docs" / "config" / "reference.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_reference() + "\n", encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
