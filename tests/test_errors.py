"""Tests for the partial_recall.errors exception hierarchy."""

from __future__ import annotations

from partial_recall.errors import (
    ConfigError,
    CorpusAdapterError,
    CorpusUnavailableError,
    EmbeddingProviderAuthError,
    EmbeddingProviderError,
    EmbeddingProviderNetworkError,
    EmbeddingProviderRateLimitError,
    IndexLockedError,
    IndexNotReadyError,
    PartialRecallError,
    SchemaVersionMismatchError,
    VectorStoreError,
)


class TestExceptionHierarchy:
    def test_base_class_default_exit_code(self) -> None:
        e = PartialRecallError("boom")
        assert e.exit_code == 1
        assert e.actionable_hint == ""

    def test_config_error_exit_code(self) -> None:
        assert ConfigError("x").exit_code == 2

    def test_provider_subclass_inherits_provider_error(self) -> None:
        for cls in (
            EmbeddingProviderAuthError,
            EmbeddingProviderNetworkError,
            EmbeddingProviderRateLimitError,
        ):
            assert issubclass(cls, EmbeddingProviderError)
            assert issubclass(cls, PartialRecallError)

    def test_corpus_unavailable_inherits_corpus_adapter_error(self) -> None:
        assert issubclass(CorpusUnavailableError, CorpusAdapterError)
        assert issubclass(CorpusUnavailableError, PartialRecallError)

    def test_schema_version_mismatch_inherits_vector_store_error(self) -> None:
        assert issubclass(SchemaVersionMismatchError, VectorStoreError)

    def test_index_not_ready_has_actionable_hint(self) -> None:
        assert "partial-recall index" in IndexNotReadyError().actionable_hint

    def test_index_locked_has_actionable_hint(self) -> None:
        assert "another" in IndexLockedError().actionable_hint.lower()

    def test_embedding_auth_error_hint_mentions_init_or_env(self) -> None:
        hint = EmbeddingProviderAuthError().actionable_hint
        assert "init" in hint or "PARTIAL_RECALL_GEMINI_API_KEY" in hint
