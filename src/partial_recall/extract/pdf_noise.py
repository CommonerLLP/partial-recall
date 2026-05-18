"""pypdf-noise filter.

pypdf emits a stream of WARNING-level log records when it encounters
malformed PDFs (cross-reference table mis-pointers, font CMap parsing
errors, broken stream lengths, etc.). These are honest reports of work
the library had to do to recover the text — recovery succeeds; the
indexer gets its text — but the raw messages are unreadable to a
scholar:

    Ignoring wrong pointing object 8 0 (offset 0)
    Skipping broken line b'01dd   01dd   1d505': Odd-length string

This module provides a logging filter that:

  * intercepts those records
  * counts them by category
  * suppresses the raw message
  * exposes a summary the CLI prints in plain English at end of run

Usage:

    with PypdfNoiseFilter() as noise:
        ...  # do indexing work
    if noise.total > 0:
        console.print(noise.human_summary())
"""

from __future__ import annotations

import logging
from collections import Counter
from contextlib import AbstractContextManager
from types import TracebackType

_NOISE_CATEGORIES: dict[str, str] = {
    # substring → human-readable category
    "Ignoring wrong pointing object": "malformed cross-reference table",
    "Skipping broken line": "broken font character map",
    "incorrect startxref": "misplaced cross-reference pointer",
    "Multiple definitions in dictionary": "duplicate dictionary entries",
    "Object": "stream parsing recovery",
}


def _categorise(msg: str) -> str:
    for needle, category in _NOISE_CATEGORIES.items():
        if needle in msg:
            return category
    return "other recovery"


class _CountingFilter(logging.Filter):
    """Filter that records each noise event and suppresses output."""

    def __init__(self) -> None:
        super().__init__()
        self.counts: Counter[str] = Counter()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 — defensive
            msg = ""
        self.counts[_categorise(msg)] += 1
        # Returning False drops the record so handlers don't emit it.
        return False


class PypdfNoiseFilter(AbstractContextManager["PypdfNoiseFilter"]):
    """Context manager: route pypdf warnings into a counter.

    On exit, leaves pypdf's logger restored. The filter's counts and
    summary are accessible via attributes on the returned object.
    """

    def __init__(self, logger_name: str = "pypdf") -> None:
        self._logger_name = logger_name
        self._filter = _CountingFilter()
        self._installed_on: list[logging.Logger] = []

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._filter.counts)

    @property
    def total(self) -> int:
        return sum(self._filter.counts.values())

    def human_summary(self) -> str:
        """One-paragraph plain-English summary suitable for terminal output."""
        if self.total == 0:
            return "All PDFs read cleanly."
        lines = [
            f"Recovered text from PDFs with structural issues "
            f"({self.total} total recovery events across the run):"
        ]
        for category, n in sorted(self._filter.counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"  • {n} × {category}")
        lines.append(
            "This is normal — text extraction succeeded; nothing was skipped."
        )
        return "\n".join(lines)

    def __enter__(self) -> PypdfNoiseFilter:
        # Attach to the pypdf logger and any common sub-loggers so we catch
        # records regardless of which submodule emits them.
        for name in (self._logger_name, f"{self._logger_name}.generic",
                     f"{self._logger_name}._cmap"):
            log = logging.getLogger(name)
            log.addFilter(self._filter)
            self._installed_on.append(log)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for log in self._installed_on:
            log.removeFilter(self._filter)
        self._installed_on.clear()
