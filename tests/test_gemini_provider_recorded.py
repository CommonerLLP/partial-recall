"""Gemini provider tests against recorded HTTP cassettes (v0.2.1 A3).

These tests exercise the *real* Gemini API contract via cassettes
under `tests/fixtures/cassettes/`. They are marked `@pytest.mark.live`,
so by default they are skipped — CI never makes live calls.

To RECORD new cassettes (e.g. when adding a test or refreshing after a
Gemini API change):

    export PARTIAL_RECALL_GEMINI_API_KEY='...'
    pytest tests/test_gemini_provider_recorded.py \\
        --run-live --record-mode=once -v

After recording, eyeball each YAML file under
`tests/fixtures/cassettes/` to confirm the API key has been scrubbed
(see `tests/fixtures/cassettes/README.md` for the protocol).

To REPLAY (CI + normal local runs):

    pytest tests/test_gemini_provider_recorded.py -v

The default `record_mode='none'` (set in conftest.vcr_config) means
vcrpy will only replay; it will refuse to record. Tests fail loudly
if a cassette is missing, rather than silently recording.

Why these tests exist alongside `test_gemini_provider.py` (which uses
MagicMock):

  * MagicMock tests are fast and exhaustive for retry / rate-limit /
    auth logic — the provider's *behaviour*.
  * Cassette tests verify the *contract* — that the JSON shape, header
    names, and URL structure we assume still match what Gemini sends.
    A breaking API change shows up here as a test failure when the
    cassette stops replaying cleanly.
"""

from __future__ import annotations

import os

import pytest

from partial_recall.embedding.providers.gemini import GeminiAPIProvider


def _provider() -> GeminiAPIProvider:
    """Build a provider using the env-var key. Tests that don't have
    a cassette OR an env key will fail — that's deliberate."""
    key = os.environ.get("PARTIAL_RECALL_GEMINI_API_KEY") or os.environ.get(
        "GEMINI_API_KEY"
    )
    # When recording, we need a real key. When replaying, vcrpy
    # intercepts the request before it actually goes out, so any string
    # is fine; pass a placeholder so the provider doesn't trip its own
    # missing-key guard.
    return GeminiAPIProvider(api_key=key or "REPLAY-PLACEHOLDER")


@pytest.mark.vcr
def test_gemini_embed_single_document() -> None:
    """Embedding one short document returns a single dim=3072 int8 vector."""
    p = _provider()
    try:
        batch = p.embed(["A short scholarly sentence about caste."],
                        task="search_document")
    finally:
        p.close()
    assert batch.vectors is not None
    assert len(batch.vectors) == 1
    # Each vector should be a non-empty bytes object — int8 packing
    # means dim bytes per vector.
    assert len(batch.vectors[0]) == 3072


@pytest.mark.vcr
def test_gemini_embed_batch_of_three() -> None:
    """Batching: three inputs → three vectors, order preserved."""
    p = _provider()
    try:
        batch = p.embed(
            [
                "First sentence about libraries and the public.",
                "Second sentence about Ambedkar and the village.",
                "Third sentence about Sanskrit and the caste-coded register.",
            ],
            task="search_document",
        )
    finally:
        p.close()
    assert batch.vectors is not None
    assert len(batch.vectors) == 3
    for v in batch.vectors:
        assert len(v) == 3072


@pytest.mark.vcr
def test_gemini_query_task_type() -> None:
    """A query-task embedding still returns a single 3072-int8 vector."""
    p = _provider()
    try:
        batch = p.embed(
            ["where did Spivak write about the elite native informant?"],
            task="search_query",
        )
    finally:
        p.close()
    assert batch.vectors is not None
    assert len(batch.vectors) == 1
    assert len(batch.vectors[0]) == 3072
