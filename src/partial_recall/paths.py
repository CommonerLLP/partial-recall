"""Platform-aware path resolution for partial-recall.

Uses platformdirs to derive correct locations per OS:
- macOS:    ~/Library/Application Support/partial-recall/
- Linux:    $XDG_CONFIG_HOME/partial-recall/ (default ~/.config/)
- Windows:  %APPDATA%\\partial-recall\\

Never hardcode paths; always go through this module.
"""

from __future__ import annotations  # noqa: I001

from pathlib import Path

from platformdirs import (
    user_cache_dir as _user_cache_dir,
    user_config_dir as _user_config_dir,
    user_data_dir as _user_data_dir,
    user_log_dir as _user_log_dir,
)

APP_NAME = "partial-recall"
APP_AUTHOR = "Commoner LLP"


def user_config_dir() -> Path:
    """Where config.toml lives."""
    return Path(_user_config_dir(APP_NAME, APP_AUTHOR))


def user_data_dir() -> Path:
    """Where vectors.sqlite lives by default."""
    return Path(_user_data_dir(APP_NAME, APP_AUTHOR))


def log_dir() -> Path:
    """Where structlog JSONL logs live."""
    return Path(_user_log_dir(APP_NAME, APP_AUTHOR))


def model_cache_dir() -> Path:
    """Where downloaded ONNX models are cached."""
    return Path(_user_cache_dir(APP_NAME, APP_AUTHOR)) / "models"


def download_cache_dir() -> Path:
    """Where downloaded attachments are cached."""
    return Path(_user_cache_dir(APP_NAME, APP_AUTHOR)) / "downloads"


def config_path() -> Path:
    """Absolute path to config.toml."""
    return user_config_dir() / "config.toml"


def default_vector_db_path() -> Path:
    """Default location for vectors.sqlite."""
    return user_data_dir() / "vectors.sqlite"


def ensure_parent_directory(path: Path) -> None:
    """Create the parent directory of `path` if it doesn't exist. Idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
