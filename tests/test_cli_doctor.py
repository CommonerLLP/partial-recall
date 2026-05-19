"""Tests for `partial-recall doctor` (v0.2.0 D1)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from partial_recall.cli.app import app
from partial_recall.cli.doctor import (
    CheckResult,
    _check_active_run_matches_config,
    _check_config_present,
    _check_embedding_provider,
    _check_folder_source,
    _check_python_version,
    _check_vector_store,
    _check_zotero_source,
    run_all_checks,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


_SAMPLE_CONFIG_TPL = """\
config_schema_version = 1

[embedding]
provider = "{provider}"
model = "{model}"
quantization = "int8"
batch_size = 32
max_input_tokens = 2048

[index]
vector_db_path = "{vector_db_path}"
allow_external_volume = false
chunker = "recursive-char-1024-128-v1"
chunk_size = 1024
chunk_overlap = 128

[zotero]
enabled = {zotero_enabled}
sqlite_path = "{zotero_sqlite}"
storage_path = "{zotero_storage}"

[folder]
enabled = {folder_enabled}
paths = [{folder_paths}]
recursive = true
extensions = [".pdf", ".txt", ".md"]

[server]
transport = "stdio"
auth_mode = "none"

[logging]
level = "INFO"
format = "human"
"""


def _write_config(
    tmp_path: Path,
    *,
    provider: str = "local-onnx",
    model: str = "intfloat/multilingual-e5-small",
    vector_db_path: Path | None = None,
    zotero_enabled: bool = False,
    zotero_sqlite: Path | None = None,
    zotero_storage: Path | None = None,
    folder_enabled: bool = False,
    folder_paths: list[Path] | None = None,
) -> Path:
    """Write a TOML config and return its path."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        _SAMPLE_CONFIG_TPL.format(
            provider=provider,
            model=model,
            vector_db_path=(vector_db_path or tmp_path / "vectors.sqlite").as_posix(),
            zotero_enabled=str(zotero_enabled).lower(),
            zotero_sqlite=(zotero_sqlite or (tmp_path / "z.sqlite")).as_posix(),
            zotero_storage=(zotero_storage or (tmp_path / "storage")).as_posix(),
            folder_enabled=str(folder_enabled).lower(),
            folder_paths=", ".join(
                f'"{p.as_posix()}"' for p in (folder_paths or [])
            ),
        ),
        encoding="utf-8",
    )
    return cfg_path


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip Gemini key env vars so checks see a clean slate."""
    monkeypatch.delenv("PARTIAL_RECALL_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def test_python_version_check_ok() -> None:
    r = _check_python_version()
    assert r.status == "ok"
    assert "3.11" in r.message or "3.12" in r.message or "3.13" in r.message


def test_config_present_ok(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path)
    r = _check_config_present(cfg_path)
    assert r.status == "ok"


def test_config_missing_fails(tmp_path: Path) -> None:
    r = _check_config_present(tmp_path / "nope.toml")
    assert r.status == "fail"
    assert "not found" in r.message
    assert r.hint is not None


def test_config_malformed_fails(tmp_path: Path) -> None:
    bad = tmp_path / "config.toml"
    bad.write_text("this is = not valid =\n  toml [[ at all", encoding="utf-8")
    r = _check_config_present(bad)
    assert r.status == "fail"


def test_embedding_provider_gemini_missing_key(
    tmp_path: Path, clean_env: None
) -> None:
    from partial_recall.config.loader import load_config
    cfg = load_config(_write_config(tmp_path, provider="gemini"))
    r = _check_embedding_provider(cfg)
    assert r.status == "fail"
    assert "no API key is configured" in r.message
    assert r.hint is not None


def test_embedding_provider_gemini_ok_with_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from partial_recall.config.loader import load_config
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "AIzaSy" + "x" * 33)
    cfg = load_config(_write_config(tmp_path, provider="gemini"))
    r = _check_embedding_provider(cfg)
    assert r.status == "ok"


def test_embedding_provider_gemini_warns_on_bad_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from partial_recall.config.loader import load_config
    monkeypatch.setenv("PARTIAL_RECALL_GEMINI_API_KEY", "garbage")
    cfg = load_config(_write_config(tmp_path, provider="gemini"))
    r = _check_embedding_provider(cfg)
    assert r.status == "warn"


def test_vector_store_missing_warns(tmp_path: Path) -> None:
    from partial_recall.config.loader import load_config
    cfg = load_config(_write_config(
        tmp_path, vector_db_path=tmp_path / "never_built.sqlite"
    ))
    r = _check_vector_store(cfg)
    assert r.status == "warn"
    assert "no indexing has run yet" in r.message


def test_vector_store_ok_when_built(tmp_path: Path) -> None:
    """Create a real VectorStore, run a tiny pipeline, then doctor it."""
    from partial_recall.config.loader import load_config
    from partial_recall.store.vector_store import VectorStore
    db = tmp_path / "vectors.sqlite"
    s = VectorStore(db)
    rid = s.create_run(
        provider="fake", model_name="fake-m", model_version="v",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine", chunker_name="c", chunker_version="c",
        started_at="2026-05-18T00:00:00",
    )
    s.activate_run(rid)
    s.close()
    cfg = load_config(_write_config(tmp_path, vector_db_path=db))
    r = _check_vector_store(cfg)
    assert r.status == "ok"
    assert "active run_id" in r.message


def test_active_run_provider_mismatch_warns(tmp_path: Path) -> None:
    """The cookjohn-imported → gemini mismatch case."""
    from partial_recall.config.loader import load_config
    from partial_recall.store.vector_store import VectorStore
    db = tmp_path / "vectors.sqlite"
    s = VectorStore(db)
    rid = s.create_run(
        provider="cookjohn-imported", model_name="gemini-embedding-001",
        model_version=None, dimensions=3072, quantization="int8",
        normalized=True, distance_metric="cosine", chunker_name="c",
        chunker_version="c", started_at="2026-05-18T00:00:00",
    )
    s.activate_run(rid)
    s.close()
    cfg = load_config(_write_config(
        tmp_path, provider="gemini", model="gemini-embedding-001",
        vector_db_path=db,
    ))
    r = _check_active_run_matches_config(cfg)
    assert r.status == "warn"
    assert "differs from config" in r.message
    assert "--allow-provider-mismatch" in (r.hint or "")


def test_zotero_source_skip_when_disabled(tmp_path: Path) -> None:
    from partial_recall.config.loader import load_config
    cfg = load_config(_write_config(tmp_path, zotero_enabled=False))
    r = _check_zotero_source(cfg)
    assert r.status == "skip"


def test_zotero_source_fail_when_missing(tmp_path: Path) -> None:
    from partial_recall.config.loader import load_config
    cfg = load_config(_write_config(
        tmp_path, zotero_enabled=True,
        zotero_sqlite=tmp_path / "nope.sqlite",
    ))
    r = _check_zotero_source(cfg)
    assert r.status == "fail"


def test_folder_source_fail_when_empty(tmp_path: Path) -> None:
    from partial_recall.config.loader import load_config
    cfg = load_config(_write_config(
        tmp_path, folder_enabled=True, folder_paths=[],
    ))
    r = _check_folder_source(cfg)
    assert r.status == "fail"
    assert "paths is empty" in r.message


def test_folder_source_fail_when_path_missing(tmp_path: Path) -> None:
    from partial_recall.config.loader import load_config
    cfg = load_config(_write_config(
        tmp_path, folder_enabled=True,
        folder_paths=[tmp_path / "nonexistent"],
    ))
    r = _check_folder_source(cfg)
    assert r.status == "fail"


def test_folder_source_ok(tmp_path: Path) -> None:
    from partial_recall.config.loader import load_config
    real = tmp_path / "library"
    real.mkdir()
    cfg = load_config(_write_config(
        tmp_path, folder_enabled=True, folder_paths=[real],
    ))
    r = _check_folder_source(cfg)
    assert r.status == "ok"


# ---------------------------------------------------------------------------
# Orchestration + CLI surface
# ---------------------------------------------------------------------------


def test_run_all_checks_returns_results_in_order(
    tmp_path: Path, clean_env: None
) -> None:
    cfg_path = _write_config(tmp_path)
    results = run_all_checks(cfg_path)
    names = [r.name for r in results]
    assert names[0] == "python_version"
    assert names[1] == "config_present"
    assert "embedding_provider" in names
    assert "vector_store" in names


def test_run_all_checks_aborts_downstream_when_config_broken(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "config.toml"
    bad.write_text("garbage [[", encoding="utf-8")
    results = run_all_checks(bad)
    names = [r.name for r in results]
    assert "downstream" in names
    # No vector_store / embedding checks should follow a broken config.
    assert "vector_store" not in names


def test_doctor_cli_json_output(tmp_path: Path, clean_env: None) -> None:
    cfg_path = _write_config(tmp_path)
    result = runner.invoke(app, ["doctor", "--config", str(cfg_path), "--json"])
    # Exit can be 0 or 1 depending on whether any check fails — we just
    # want valid JSON either way.
    assert result.exit_code in (0, 1)
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, list)
    assert all("name" in entry and "status" in entry for entry in parsed)


def test_doctor_cli_human_output_contains_table(
    tmp_path: Path, clean_env: None
) -> None:
    cfg_path = _write_config(tmp_path)
    result = runner.invoke(app, ["doctor", "--config", str(cfg_path)])
    assert "diagnostic checks" in result.stdout
    assert "python_version" in result.stdout
    assert "embedding_provider" in result.stdout


def test_doctor_cli_exits_nonzero_when_any_check_fails(
    tmp_path: Path, clean_env: None
) -> None:
    """provider=gemini + no key → fail → non-zero exit."""
    cfg_path = _write_config(tmp_path, provider="gemini")
    result = runner.invoke(app, ["doctor", "--config", str(cfg_path), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    statuses = {entry["name"]: entry["status"] for entry in payload}
    assert statuses["embedding_provider"] == "fail"


def test_check_result_is_immutable() -> None:
    """Defensive: CheckResult is frozen so consumers can't mutate results
    en route to renderers."""
    from dataclasses import FrozenInstanceError
    r = CheckResult(name="x", status="ok", message="y")
    with pytest.raises(FrozenInstanceError):
        r.status = "fail"  # type: ignore[misc]
