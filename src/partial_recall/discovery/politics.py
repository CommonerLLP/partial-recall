from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from partial_recall.discovery.releases import Release

# The Ambedkarite analytical framework explicitly identifies the Bahujan
# (SC, ST, OBC, Dalit, Adivasi) as the Numerical Majority but Political Minority.
# To counter the "numerical majority = political majority" fallacy (where elite 
# perspectives dominate the data default), we enforce visibility.
MARGINALIZED_TERMS = [
    r"\bdalits?\b", r"\badivasis?\b", r"\bbahujans?\b", 
    r"\bcaste\b", r"\buntouchab", r"\bambedkar", 
    r"\bsc/st\b", r"\bobc\b", r"\btribal\b"
]
_MARGINALIZED_RE = re.compile("|".join(MARGINALIZED_TERMS), re.IGNORECASE)

def is_marginalized_focus(release: Release) -> bool:
    """True if the text (title/subjects) signals focus on the marginalized majority."""
    text = f"{release.title} {release.subjects}"
    return bool(_MARGINALIZED_RE.search(text))

def apply_marginalized_first_positioning(releases: list[Release]) -> list[Release]:
    """Sort releases so that marginalized-focused works appear first."""
    return sorted(releases, key=lambda r: (not is_marginalized_focus(r), r.title))
