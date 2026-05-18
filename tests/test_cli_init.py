"""Tests for the CLI init wizard.

Uses Typer's CliRunner with stdin input simulation.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from partial_recall.cli.app import app
from partial_recall.config.loader import load_config

runner = CliRunner()


def test_init_writes_config_with_default_choices(tmp_path: Path) -> None:
    """User accepts all defaults: option 1 (local-onnx default), default vector
    DB path, no Zotero (will skip).
    """
    cfg_path = tmp_path / "config.toml"
    # Stdin: pick "1", press Enter for vector DB default. Zotero — auto-detect
    # may or may not find it; provide enough input for the worst case:
    stdin = "\n".join(
        [
            "1",  # provider profile: option 1 (English/Latin-script)
            "",  # accept default vector DB path
            # Zotero — auto-detect may or may not find it:
            "n",  # if "Use this?" asked: no
            "y",  # "Skip Zotero?" yes
            "",  # filler if any
        ]
    ) + "\n"
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
    assert cfg.embedding.model == "intfloat/multilingual-e5-small"


def test_init_aborts_if_existing_config_and_no_force(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("existing", encoding="utf-8")
    result = runner.invoke(
        app,
        ["init", "--config", str(cfg_path)],
        input="n\n",
    )
    assert result.exit_code == 1
    # Existing content unchanged
    assert cfg_path.read_text(encoding="utf-8") == "existing"


def test_init_disabled_profile_re_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If user picks a disabled profile, wizard re-prompts and accepts the next pick."""
    from partial_recall.cli import init as init_mod

    patched = tuple(
        replace(p, enabled=False) if i == 2 else p
        for i, p in enumerate(init_mod.PROVIDER_PROFILES)
    )
    monkeypatch.setattr(init_mod, "PROVIDER_PROFILES", patched)

    cfg_path = tmp_path / "config.toml"
    stdin = "\n".join(
        [
            "3",  # disabled profile (patched)
            "1",  # fallback to option 1
            "",  # default vector DB
            "n",  # use default Zotero? no
            "y",  # skip Zotero? yes
        ]
    ) + "\n"
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
    assert cfg.embedding.provider == "local-onnx"  # fallback to option 1


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "partial-recall" in result.stdout
