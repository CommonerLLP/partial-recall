"""Tests for GeminiAPIProvider.

We mock httpx.Client to avoid live API calls. The provider's
network/retry/auth/rate-limit logic is exercised against mocked responses.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from partial_recall.embedding.providers.gemini import GeminiAPIProvider
from partial_recall.embedding.types import DistanceMetric, Quantization
from partial_recall.errors import (
    EmbeddingProviderAuthError,
)


def _mock_response(status_code: int, body: dict[str, Any] | str) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    if isinstance(body, dict):
        r.json.return_value = body
        r.text = str(body)
    else:
        r.text = body
    return r


def _make_client(responses: list[MagicMock]) -> MagicMock:
    """Mock httpx.Client that returns the given responses in order."""
    client = MagicMock(spec=httpx.Client)
    client.post = MagicMock(side_effect=responses)
    return client


def test_resolve_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("partial_recall.secrets._keyring_get", lambda _key: None)
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "test-key-123")
    p = GeminiAPIProvider(http_client=_make_client([]))
    assert p._api_key == "test-key-123"
    p.close()


def test_missing_api_key_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("partial_recall.secrets._keyring_get", lambda _key: None)
    monkeypatch.delenv("PARTIAL_RECALL_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(EmbeddingProviderAuthError):
        GeminiAPIProvider(http_client=_make_client([]))


def test_metadata_is_3072_dim_cosine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "k")
    p = GeminiAPIProvider(http_client=_make_client([]))
    m = p.metadata
    assert m.provider == "gemini"
    assert m.dimensions == 3072
    assert m.distance_metric == DistanceMetric.COSINE
    assert p.quantization == Quantization.INT8
    p.close()


def test_embed_one_text_returns_int8_packed_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "k")
    # Mock response: 3072 floats.
    fake_vector = [0.01] * 3072
    mock_resp = _mock_response(200, {"embeddings": [{"values": fake_vector}]})
    p = GeminiAPIProvider(http_client=_make_client([mock_resp]), api_key="k")
    batch = p.embed(["library policy"], task="search_query")
    assert batch.vectors is not None
    assert len(batch.vectors) == 1
    assert len(batch.vectors[0]) == 3072  # int8 = 1 byte/dim
    p.close()


def test_embed_empty_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "k")
    p = GeminiAPIProvider(http_client=_make_client([]), api_key="k")
    batch = p.embed([], task="search_query")
    assert batch.vectors == []
    p.close()


def test_401_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "k")
    mock_resp = _mock_response(401, "Unauthorized")
    p = GeminiAPIProvider(http_client=_make_client([mock_resp]), api_key="k", max_retries=1)
    with pytest.raises(EmbeddingProviderAuthError):
        p.embed(["x"], task="search_query")
    p.close()


def test_query_vs_document_task_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "k")
    captured_payloads: list[dict[str, Any]] = []

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]) -> MagicMock:
        captured_payloads.append(json)
        return _mock_response(200, {"embeddings": [{"values": [0.0] * 3072}]})

    client = MagicMock(spec=httpx.Client)
    client.post = MagicMock(side_effect=fake_post)

    p = GeminiAPIProvider(http_client=client, api_key="k")
    p.embed(["doc"], task="search_document")
    p.embed(["query"], task="search_query")
    assert captured_payloads[0]["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert captured_payloads[1]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    p.close()
