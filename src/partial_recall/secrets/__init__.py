"""Secrets handling for partial-recall (v0.2.4 D2).

Cross-platform credential storage via the `keyring` package:
  - macOS   → Keychain
  - Linux   → Secret Service (Gnome Keyring / KWallet)
  - Windows → Credential Manager

The CLI / provider code calls into this module rather than reaching
for `os.environ` directly. The resolution order is:

  1. The argument passed in code (tests, explicit overrides).
  2. `keyring.get_password(SERVICE_NAME, key)` if `keyring` is
     installed AND a value is set there.
  3. Environment variable fallback (the canonical name, plus a
     historical alias if relevant).

Each provider has a dedicated `keyring` key under the same service
name `"partial-recall"` so all secrets live under one Keychain /
Secret-Service entry from the user's point of view.
"""

from __future__ import annotations

import contextlib
import os

SERVICE_NAME = "partial-recall"

# Per-provider keyring KEY + the env-var names that legacy / users
# may still rely on. The env vars stay supported alongside keyring
# so existing setups keep working.
GEMINI_KEYRING_KEY = "gemini_api_key"
GEMINI_ENV_NAMES = ("PARTIAL_RECALL_GEMINI_API_KEY", "GEMINI_API_KEY")


def _keyring_get(key: str) -> str | None:
    """Read a secret from the OS keyring; return None if `keyring`
    is not installed, no backend is configured, or no value exists."""
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        value = keyring.get_password(SERVICE_NAME, key)
    except Exception:  # noqa: BLE001 — defensive against backend bugs
        return None
    return value or None


def _keyring_set(key: str, value: str) -> None:
    """Write a secret to the OS keyring; raise RuntimeError if the
    `keyring` package is not installed, so the caller surfaces an
    actionable hint instead of silently no-op'ing."""
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "The `keyring` package is not installed. "
            "Install with `pipx inject partial-recall keyring` or "
            "`pip install partial-recall[keyring]` and re-run."
        ) from e
    keyring.set_password(SERVICE_NAME, key, value)


def _keyring_delete(key: str) -> None:
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "The `keyring` package is not installed."
        ) from e
    # Delete on absent key is OK; suppress backend bugs.
    with contextlib.suppress(Exception):
        keyring.delete_password(SERVICE_NAME, key)


def get_gemini_api_key() -> str | None:
    """Resolve the Gemini API key.

    Order:
      1. keyring entry SERVICE_NAME = "partial-recall", key =
         "gemini_api_key".
      2. PARTIAL_RECALL_GEMINI_API_KEY env var.
      3. GEMINI_API_KEY env var.

    Returns None if no source has a value.
    """
    value = _keyring_get(GEMINI_KEYRING_KEY)
    if value:
        return value
    for env_name in GEMINI_ENV_NAMES:
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value
    return None


def set_gemini_api_key(value: str) -> None:
    """Persist the Gemini API key to the OS keyring."""
    if not value:
        raise ValueError("api key must be a non-empty string")
    _keyring_set(GEMINI_KEYRING_KEY, value)


def delete_gemini_api_key() -> None:
    """Remove the Gemini API key from the OS keyring (no-op if absent)."""
    _keyring_delete(GEMINI_KEYRING_KEY)


def keyring_available() -> bool:
    """True iff the `keyring` package is importable AND a real
    backend (not the null/fail backend) is configured. Used by
    `doctor` and CLI commands to give the user a clean signal."""
    try:
        import keyring  # type: ignore[import-not-found]
        from keyring.backends.fail import Keyring as FailKeyring  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001
        return False
    return not isinstance(backend, FailKeyring)
