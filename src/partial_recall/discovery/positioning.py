"""Position an incoming work against the existing corpus.

Given a candidate work's title (+ optional blurb) — metadata only, no
full text — embed it and find where it falls in what the user has
already read:

- nearest neighbours in the existing corpus,
- a density signal (dense = a well-read neighbourhood; thin/empty = a
  gap the candidate would open),
- a likely-owned flag (is a near-identical text already indexed?).

This is the headline of the discovery feature: discovery is recall
applied to the incoming stream. The function is READ-ONLY — it writes
nothing — and reuses `search.orchestrator.search`, so it shares the
active embedding run, quantization, and scoring with `semantic_search`.

Density thresholds are heuristic and embedding-model-relative (the
gemini/cookjohn run scores differently from e5). They are deliberately
conservative and the raw `top_score` / `mean_score` are always returned
alongside the label, so a consumer never has to trust the label over the
numbers. Tuning against the active run's score distribution is a later
slice.
"""

from __future__ import annotations

from dataclasses import dataclass

from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.search.orchestrator import search
from partial_recall.store.vector_store import VectorStore

# Cosine-similarity heuristics on the nearest neighbours. Provisional;
# see module docstring. Exposed as constants so a later slice can derive
# them from the active run rather than hard-coding.
LIKELY_OWNED_THRESHOLD = 0.97  # near-identical text → almost certainly already held
DENSE_TOP = 0.86               # a close neighbour exists → well-read neighbourhood
MODERATE_TOP = 0.78            # some relation exists
RELATED_BAR = MODERATE_TOP     # a neighbour at/above this counts as "related"


@dataclass(frozen=True)
class Neighbour:
    """One existing-corpus item near the candidate work."""

    score: float
    item_key: str
    corpus: str
    title: str | None
    creators: list[dict[str, str]]
    date: str | None
    source_type: str
    preview: str | None


@dataclass(frozen=True)
class Positioning:
    """Where a candidate work falls in the existing corpus."""

    query_text: str
    neighbours: list[Neighbour]
    top_score: float | None
    mean_score: float | None
    related_count: int
    density: str  # "dense" | "moderate" | "thin" | "empty"
    likely_owned: bool
    owned_match: Neighbour | None


def _classify_density(top_score: float | None, related_count: int) -> str:
    if top_score is None:
        return "empty"
    if top_score >= DENSE_TOP and related_count >= 3:
        return "dense"
    if top_score >= MODERATE_TOP:
        return "moderate"
    return "thin"


def position(
    *,
    store: VectorStore,
    provider: EmbeddingProvider,
    title: str,
    blurb: str | None = None,
    top_k: int = 10,
    corpus: str | None = None,
) -> Positioning:
    """Place a candidate work against the existing corpus.

    `title` (+ optional `blurb`) is embedded and matched against the
    active run. `corpus`, if given, restricts the neighbourhood to one
    corpus (e.g. only "zotero"); omit to position against everything the
    user has read. Raises whatever `search` raises when the index is not
    ready (IndexNotReadyError) — callers wrap it into an error payload.
    """
    parts = [p.strip() for p in (title, blurb) if p and p.strip()]
    query_text = ". ".join(parts)
    if not query_text:
        return Positioning(
            query_text="", neighbours=[], top_score=None, mean_score=None,
            related_count=0, density="empty", likely_owned=False, owned_match=None,
        )

    results = search(
        store=store, provider=provider, query=query_text, top_k=top_k, corpus=corpus,
    )

    neighbours = [
        Neighbour(
            score=r.score,
            item_key=r.item_key,
            corpus=r.corpus,
            title=r.title,
            creators=r.creators,
            date=r.date,
            source_type=r.source_type,
            preview=r.text_preview,
        )
        for r in results
    ]

    if not neighbours:
        return Positioning(
            query_text=query_text, neighbours=[], top_score=None, mean_score=None,
            related_count=0, density="empty", likely_owned=False, owned_match=None,
        )

    scores = [n.score for n in neighbours]
    top_score = max(scores)
    mean_score = sum(scores) / len(scores)
    related_count = sum(1 for s in scores if s >= RELATED_BAR)

    owned_match = neighbours[0] if neighbours[0].score >= LIKELY_OWNED_THRESHOLD else None
    likely_owned = owned_match is not None

    return Positioning(
        query_text=query_text,
        neighbours=neighbours,
        top_score=top_score,
        mean_score=mean_score,
        related_count=related_count,
        density=_classify_density(top_score, related_count),
        likely_owned=likely_owned,
        owned_match=owned_match,
    )
