import json
from pathlib import Path
from typer.testing import CliRunner
from partial_recall.cli.app import app

runner = CliRunner()

def test_cli_fetch_zotero_local(tmp_path: Path):
    """Test fetching a local file from the Zotero corpus via CLI."""
    # Write a config pointing to our test fixture
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("""
config_schema_version = 1

[embedding]
provider = "local-onnx"
model = "intfloat/multilingual-e5-small"
quantization = "int8"
batch_size = 32

[index]
vector_db_path = ""
allow_external_volume = false
chunker = "recursive-char-1024-128-v1"

[zotero]
enabled = true
sqlite_path = "tests/fixtures/zotero_snapshot/zotero.sqlite"
storage_path = "tests/fixtures/zotero_snapshot/storage"
api_key = "fake_key"
user_id = "fake_id"
    """)

    # Item 'ITEM01XX' has a PDF attachment 'PDFITEM01' in our test DB
    result = runner.invoke(app, ["fetch", "ITEM01XX", "--config", str(cfg_file), "--json"])
    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert data["item_key"] == "ITEM01XX"
    assert data["attachment_key"] == "PDFITEM01"
    assert data["source"] == "local"
    assert "paper.pdf" in data["path"]
