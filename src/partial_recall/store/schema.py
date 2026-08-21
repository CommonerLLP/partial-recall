"""Schema version metadata and migration discovery."""

from __future__ import annotations

from importlib import resources

CURRENT_SCHEMA_VERSION = 4

# Migration filenames must follow NNNN_description.sql; sorted lexicographically.
MIGRATIONS_PACKAGE = "partial_recall.store.migrations"


def load_migration(filename: str) -> str:
    """Read a migration file from the migrations package."""
    return resources.files(MIGRATIONS_PACKAGE).joinpath(filename).read_text(encoding="utf-8")


def list_migrations() -> list[str]:
    """List migration filenames in order."""
    files = sorted(
        f.name
        for f in resources.files(MIGRATIONS_PACKAGE).iterdir()
        if f.is_file() and f.name.endswith(".sql") and f.name[0].isdigit()
    )
    return files
