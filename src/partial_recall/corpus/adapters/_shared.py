"""Shared utilities for corpus adapters."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path


def stable_item_key(path: Path) -> str:
    """Short, stable, readable identifier for a file path.

    First 12 hex chars of SHA-256 of the absolute path, plus the
    lowercased alphanumeric stem — unique within a corpus and stable
    across runs as long as the file path does not change.
    """
    h = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    stem = "".join(c if c.isalnum() else "_" for c in path.stem.lower())[:30]
    return f"{h}-{stem}" if stem else h


def read_ignorefile(path: Path) -> list[str]:
    """Return non-blank, non-comment lines from a .partial-recallignore."""
    if not path.exists():
        return []
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def matches_any(rel: str, patterns: list[str]) -> bool:
    """Match a POSIX-relative path against gitignore-style globs."""
    if not patterns:
        return False
    for pat in patterns:
        p = pat.lstrip("./")
        if fnmatch.fnmatch(rel, p):
            return True
        if p.endswith("/") and (rel.startswith(p) or rel == p.rstrip("/")):
            return True
    return False
