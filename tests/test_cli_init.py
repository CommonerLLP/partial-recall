"""Tests for the CLI init wizard.

Uses Typer's CliRunner with stdin input simulation.
The wizard now has a hardware-aware, language-aware ladder:
  1) corpus language group (1-4)
  2) model choice from the ranked list (1-N)
  3) vector DB path (Enter for default)
  4) Zotero (skip)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from partial_recall.cli.app import app
from partial_recall.config.loader import load_config

runner = CliRunner()


def _mock_hardware(
    monkeypatch: pytest.MonkeyPatch, ram_gb: float = 8.0, apple: bool = False
) -> None:
    from partial_recall.hardware import HardwareProfile
    hw = HardwareProfile(ram_gb=ram_gb, is_apple_silicon=apple, tier="standard")
    monkeypatch.setattr("partial_recall.cli.init.detect_hardware", lambda: hw)


def test_init_writes_config_latin_corpus_minimal_ram(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Latin corpus + 4 GB RAM → e5-small recommended and chosen."""
    from partial_recall.hardware import HardwareProfile
    hw = HardwareProfile(ram_gb=4.0, is_apple_silicon=False, tier="minimal")
    monkeypatch.setattr("partial_recall.cli.init.detect_hardware", lambda: hw)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    cfg_path = tmp_path / "config.toml"
    stdin = "\n".join([
        "1",   # corpus language: Latin-script
        "1",   # model choice: recommended (e5-small on minimal)
        "",    # accept default vector DB path
        "y",   # skip Zotero
    ]) + "\n"
    result = runner.invoke(
        app,
        ["init", "--config", str(cfg_path), "--force", "--allow-external-volume"],
        input=stdin,
    )
    if result.exit_code != 0:
        print("STDOUT:", result.stdout)
        print("EXCEPTION:", result.exception)
    assert result.exit_code == 0
    assert cfg_path.exists()
    cfg = load_config(cfg_path)
    assert cfg.embedding.provider == "local-onnx"
    assert "multilingual-e5-small" in cfg.embedding.model


def test_init_writes_config_south_asian_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """South Asian corpus + 8 GB RAM → LaBSE or BGE-M3 at top; pick option 1."""
    _mock_hardware(monkeypatch, ram_gb=8.0)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    cfg_path = tmp_path / "config.toml"
    stdin = "\n".join([
        "2",   # corpus language: South Asian scripts
        "1",   # pick top recommendation
        "",    # default vector DB path
        "y",   # skip Zotero
    ]) + "\n"
    result = runner.invoke(
        app,
        ["init", "--config", str(cfg_path), "--force", "--allow-external-volume"],
        input=stdin,
    )
    if result.exit_code != 0:
        print("STDOUT:", result.stdout)
        print("EXCEPTION:", result.exception)
    assert result.exit_code == 0
    cfg = load_config(cfg_path)
    # Top pick for south_asian + 8 GB should be LaBSE or BGE-M3
    assert cfg.embedding.provider == "sentence-transformer"
    assert cfg.embedding.model in (
        "sentence-transformers/LaBSE",
        "BAAI/bge-m3",
    )


def test_init_powerful_apple_silicon_south_asian(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """16 GB Apple Silicon + South Asian corpus → BGE-M3 recommended."""
    from partial_recall.hardware import HardwareProfile
    hw = HardwareProfile(ram_gb=16.0, is_apple_silicon=True, tier="powerful")
    monkeypatch.setattr("partial_recall.cli.init.detect_hardware", lambda: hw)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    cfg_path = tmp_path / "config.toml"
    stdin = "\n".join([
        "2",   # South Asian scripts
        "1",   # top recommendation
        "",    # default vector DB path
        "y",   # skip Zotero
    ]) + "\n"
    result = runner.invoke(
        app,
        ["init", "--config", str(cfg_path), "--force", "--allow-external-volume"],
        input=stdin,
    )
    if result.exit_code != 0:
        print("STDOUT:", result.stdout)
        print("EXCEPTION:", result.exception)
    assert result.exit_code == 0
    cfg = load_config(cfg_path)
    assert cfg.embedding.provider == "sentence-transformer"
    assert cfg.embedding.model == "BAAI/bge-m3"


def test_init_aborts_if_existing_config_and_no_force(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("existing", encoding="utf-8")
    result = runner.invoke(
        app,
        ["init", "--config", str(cfg_path)],
        input="n\n",
    )
    assert result.exit_code == 1
    assert cfg_path.read_text(encoding="utf-8") == "existing"


def test_init_custom_model_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User picks the 'Enter manually' option and types a custom model name."""
    _mock_hardware(monkeypatch, ram_gb=8.0)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Find out how many options the standard corpus produces to pick the custom idx.
    # Rather than hardcoding, just pick a very high number and let the wizard
    # re-prompt. Instead, we pass a large-enough number.
    # The custom option is always the last numbered item.
    # For simplicity, we use "4" (mixed) language which shows all options,
    # and the custom option is last. We'll drive enough "next" to get there
    # by using the CliRunner's input stream.
    # Custom option index for standard tier with mixed language = 5 (bge-m3, LaBSE,
    # e5-large, e5-small, gemini, custom). Let's just count: 5 options + custom = 6.
    cfg_path = tmp_path / "config.toml"
    stdin = "\n".join([
        "4",                              # mixed corpus
        "6",                              # custom model (6th option = after 5 catalogue entries)
        "2",                              # provider: sentence-transformer
        "google/muril-base-cased",        # model name
        "",                               # default vector DB
        "y",                              # skip Zotero
    ]) + "\n"
    result = runner.invoke(
        app,
        ["init", "--config", str(cfg_path), "--force", "--allow-external-volume"],
        input=stdin,
    )
    if result.exit_code != 0:
        print("STDOUT:", result.stdout)
        print("EXCEPTION:", result.exception)
    assert result.exit_code == 0
    cfg = load_config(cfg_path)
    assert cfg.embedding.provider == "sentence-transformer"
    assert cfg.embedding.model == "google/muril-base-cased"


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "partial-recall" in result.stdout
