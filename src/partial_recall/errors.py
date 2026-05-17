"""Typed exception hierarchy for partial-recall.

Every exception carries:
- exit_code: process exit code if the CLI catches this exception
- actionable_hint: short human-readable suggestion for the user

The CLI's top-level error handler prints the message + actionable_hint,
suppressing the traceback unless --verbose is set.
"""

from __future__ import annotations


class PartialRecallError(Exception):
    """Base exception for all partial-recall errors."""

    exit_code: int = 1
    actionable_hint: str = ""


class ConfigError(PartialRecallError):
    """Configuration file is missing, malformed, or schema-incompatible."""

    exit_code = 2


class EmbeddingProviderError(PartialRecallError):
    """Base for embedding-provider failures."""


class EmbeddingProviderNetworkError(EmbeddingProviderError):
    actionable_hint = (
        "Check network connectivity and try again. "
        "Use --resume to continue indexing."
    )


class EmbeddingProviderAuthError(EmbeddingProviderError):
    actionable_hint = (
        "Run `partial-recall init` to reconfigure your API key, "
        "or check PARTIAL_RECALL_GEMINI_API_KEY env var."
    )


class EmbeddingProviderRateLimitError(EmbeddingProviderError):
    actionable_hint = (
        "Rate limit reached. The indexer will back off automatically. "
        "Use --resume to continue if it stopped."
    )


class CorpusAdapterError(PartialRecallError):
    """Base for corpus-adapter failures."""


class CorpusUnavailableError(CorpusAdapterError):
    actionable_hint = (
        "Check that the corpus source exists and is readable. "
        "For Zotero, ensure zotero.sqlite is at the configured path."
    )


class VectorStoreError(PartialRecallError):
    """Base for vector-store failures."""


class SchemaVersionMismatchError(VectorStoreError):
    actionable_hint = (
        "Your vector DB schema is older than this version of partial-recall "
        "expects. Migration will run automatically; back up vectors.sqlite "
        "first if you want to be safe."
    )


class IndexNotReadyError(PartialRecallError):
    actionable_hint = "No vectors found. Run `partial-recall index` first."


class IndexLockedError(PartialRecallError):
    actionable_hint = (
        "Another indexing process is running. Wait for it, or stop it with Ctrl-C."
    )
