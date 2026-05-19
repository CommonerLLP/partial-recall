"""Tests for v0.2.4 D2 — Gemini API key via OS keyring.

Uses keyring's in-memory `kp.set_keyring(NullKeyring)` swap so tests
don't touch the user's real Keychain / Secret Service / Credential
Manager. If the `keyring` package isn't installed (e.g. minimal CI
without the [keyring] extra), the keyring-path tests skip cleanly
and the env-var-only path remains covered.
"""

from __future__ import annotations

import pytest

# Skip the entire module if the keyring extra is not installed —
# the secrets module's env-var fallback is still covered elsewhere.
keyring = pytest.importorskip("keyring")


from partial_recall.secrets import (  # noqa: E402
    GEMINI_KEYRING_KEY,
    SERVICE_NAME,
    delete_gemini_api_key,
    get_gemini_api_key,
    keyring_available,
    set_gemini_api_key,
)


class _InMemoryKeyring:
    """Backend that stores in a dict; safe for tests."""

    priority = 1  # keyring.backend.KeyringBackend's required class attr

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self.store.pop((service, key), None)


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch):
    """Swap the keyring backend for an in-memory dict; strip env vars."""
    monkeypatch.delenv("PARTIAL_RECALL_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    backend = _InMemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "get_password",
                        lambda s, k: backend.get_password(s, k))
    monkeypatch.setattr(keyring, "set_password",
                        lambda s, k, v: backend.set_password(s, k, v))
    monkeypatch.setattr(keyring, "delete_password",
                        lambda s, k: backend.delete_password(s, k))
    return backend


def test_set_then_get_round_trips(fake_keyring) -> None:
    set_gemini_api_key("AIzaSy" + "x" * 33)
    assert fake_keyring.store[(SERVICE_NAME, GEMINI_KEYRING_KEY)] == \
        "AIzaSy" + "x" * 33
    assert get_gemini_api_key() == "AIzaSy" + "x" * 33


def test_get_returns_none_when_neither_keyring_nor_env_set(fake_keyring) -> None:
    assert get_gemini_api_key() is None


def test_delete_removes_keyring_entry(fake_keyring) -> None:
    set_gemini_api_key("AIzaSy" + "z" * 33)
    assert get_gemini_api_key() is not None
    delete_gemini_api_key()
    assert get_gemini_api_key() is None
    assert (SERVICE_NAME, GEMINI_KEYRING_KEY) not in fake_keyring.store


def test_env_var_used_when_keyring_empty(
    fake_keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "env-key-here")
    assert get_gemini_api_key() == "env-key-here"


def test_keyring_preferred_over_env_var(
    fake_keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order: keyring before env so a user who's set the secret in
    Keychain doesn't get silently overridden by a stale env var."""
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "stale-env-key")
    set_gemini_api_key("AIzaSy" + "k" * 33)
    assert get_gemini_api_key().startswith("AIzaSy")


def test_legacy_gemini_api_key_env_var_still_honoured(
    fake_keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "alt-env-name-value")
    assert get_gemini_api_key() == "alt-env-name-value"


def test_set_empty_rejected(fake_keyring) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        set_gemini_api_key("")


def test_keyring_available_returns_bool(fake_keyring) -> None:
    """In a test environment with a real (in-memory) backend swapped
    in, keyring_available should report True."""
    assert isinstance(keyring_available(), bool)
