"""Tests for partial_recall.paths."""

from __future__ import annotations

from pathlib import Path

from partial_recall.paths import (
    APP_NAME,
    config_path,
    log_dir,
    model_cache_dir,
    user_data_dir,
)


def test_app_name_is_partial_recall() -> None:
    assert APP_NAME == "partial-recall"


def test_config_path_ends_with_config_toml() -> None:
    p = config_path()
    assert p.name == "config.toml"


def test_user_data_dir_includes_app_name() -> None:
    p = user_data_dir()
    assert APP_NAME in str(p)


def test_log_dir_includes_app_name() -> None:
    p = log_dir()
    assert APP_NAME in str(p)


def test_model_cache_dir_ends_with_models() -> None:
    p = model_cache_dir()
    assert p.name == "models"


def test_ensure_parent_directory_creates_missing(tmp_path: Path) -> None:
    from partial_recall.paths import ensure_parent_directory
    target = tmp_path / "a" / "b" / "c.toml"
    assert not target.parent.exists()
    ensure_parent_directory(target)
    assert target.parent.exists()
    assert not target.exists()  # only parent created
