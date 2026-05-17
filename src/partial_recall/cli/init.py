"""First-run wizard: `partial-recall init`.

Walks the user through choosing an embedding provider profile, vector DB
location (with external-volume warning), Zotero auto-detect, optional
folder source, and MCP integration snippet. Writes config.toml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt

from partial_recall.config.loader import save_config
from partial_recall.config.models import (
    EmbeddingConfig,
    EmbeddingProviderName,
    FolderConfig,
    IndexConfig,
    LoggingConfig,
    PartialRecallConfig,
    ServerConfig,
    ZoteroConfig,
)
from partial_recall.paths import (
    config_path,
    default_vector_db_path,
)

console = Console()


@dataclass(frozen=True)
class ProviderProfile:
    label: str
    description: str
    provider: EmbeddingProviderName
    model: str
    enabled: bool = True


PROVIDER_PROFILES: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        label="Most reading in English / Latin-script European",
        description="local model, ~470 MB download, no API key, free  [recommended]",
        provider="local-onnx",
        model="intfloat/multilingual-e5-small",
    ),
    ProviderProfile(
        label="Multilingual including South Asian / African / Indigenous corpora",
        description="local model (covers 100+ languages), same as above",
        provider="local-onnx",
        model="intfloat/multilingual-e5-small",
    ),
    ProviderProfile(
        label="Highest quality, willing to use Google Cloud (paid)",
        description="Gemini API, requires internet + Google Cloud account [coming in v0.1.0]",
        provider="gemini",
        model="gemini-embedding-001",
        enabled=False,
    ),
    ProviderProfile(
        label="I want to pick a specific model (advanced)",
        description="raw model name; you must know what you're doing",
        provider="local-onnx",
        model="",
    ),
)


def init_command(
    force: bool = typer.Option(  # noqa: B008 — Typer requires call-in-default
        False, "--force", help="Overwrite existing config without confirmation."
    ),
    config: Path | None = typer.Option(  # noqa: B008 — Typer pattern
        None, "--config", help="Write to this path instead of platform default."
    ),
    allow_external_volume: bool = typer.Option(  # noqa: B008 — Typer pattern
        False,
        "--allow-external-volume",
        help="Allow vector DB on external/removable volume without interactive ack.",
    ),
) -> None:
    """Run the first-run wizard. Writes config.toml at the platform default path
    (or --config PATH if given). Use --force to overwrite an existing file.
    """
    cfg_path = config if config else config_path()

    if (
        cfg_path.exists()
        and not force
        and not Confirm.ask(
            f"Config already exists at {cfg_path}. Overwrite?", default=False
        )
    ):
        console.print("[yellow]aborted.[/yellow]")
        raise typer.Exit(code=1)

    console.print(
        "[bold]Welcome to partial-recall.[/bold] "
        "Setting up semantic search for your scholarly corpus.\n"
    )
    console.print(
        "This tool runs entirely on your machine by default. No data leaves your "
        "laptop unless you explicitly choose a cloud embedding provider.\n"
    )

    # 1. Embedding provider profile
    profile = _ask_provider_profile()
    provider_name: EmbeddingProviderName
    if profile.label.startswith("I want to pick"):
        model_name = Prompt.ask(
            "Enter the HuggingFace model name",
            default="intfloat/multilingual-e5-small",
        )
        provider_name = "local-onnx"
    else:
        model_name = profile.model
        provider_name = profile.provider

    # 2. Vector DB location
    vector_db_path = _ask_vector_db_path(
        allow_external_volume=allow_external_volume
    )

    # 3. Zotero auto-detect
    zotero_cfg = _ask_zotero()

    # 4. Folder (skipped for v0.0.1 — FolderAdapter is v0.1.0)
    folder_cfg = FolderConfig(enabled=False)

    # 5. Assemble + save
    cfg = PartialRecallConfig(
        embedding=EmbeddingConfig(provider=provider_name, model=model_name),
        index=IndexConfig(vector_db_path=vector_db_path),
        zotero=zotero_cfg,
        folder=folder_cfg,
        server=ServerConfig(),
        logging=LoggingConfig(),
    )
    save_config(cfg, cfg_path)
    console.print(f"\n[green]✓[/green] Wrote config to {cfg_path}\n")

    # 6. MCP client integration snippet
    _print_mcp_integration_snippet()


def _ask_provider_profile() -> ProviderProfile:
    console.print("[bold]How will you use partial-recall?[/bold]\n")
    for i, p in enumerate(PROVIDER_PROFILES, start=1):
        marker = " " if p.enabled else "x"
        console.print(f"  [{marker}] {i}) {p.label}")
        console.print(f"        [dim]{p.description}[/dim]\n")
    while True:
        choice = IntPrompt.ask("Choose", default=1, choices=["1", "2", "3", "4"])
        prof = PROVIDER_PROFILES[choice - 1]
        if not prof.enabled:
            console.print(
                f"[yellow]Option {choice} is not yet available in v0.0.1. "
                "Please pick another.[/yellow]"
            )
            continue
        return prof


def _ask_vector_db_path(*, allow_external_volume: bool) -> Path:
    default = default_vector_db_path()
    console.print("\n[bold]Where should the vector index live?[/bold]")
    console.print(f"Default: {default}")
    custom = Prompt.ask(
        "Press Enter to accept, or type a custom path", default=str(default)
    )
    p = Path(custom).expanduser().resolve()
    # Warn if external volume on macOS (/Volumes/<not-Macintosh-HD>/...)
    if str(p).startswith("/Volumes/") and not str(p).startswith(
        "/Volumes/Macintosh HD/"
    ):
        console.print(
            f"\n[yellow]!  {p} is on an external volume.\n"
            "   On macOS this can cause sandbox / sleep-throttling issues.\n"
            "   (We saw this with cookjohn's vector DB earlier.)[/yellow]"
        )
        if not allow_external_volume and not Confirm.ask(
            "Are you sure?", default=False
        ):
            raise typer.Exit(code=1)
    return p


def _ask_zotero() -> ZoteroConfig:
    default_zotero = Path.home() / "Zotero"
    default_sqlite = default_zotero / "zotero.sqlite"
    default_storage = default_zotero / "storage"
    console.print("\n[bold]Zotero[/bold]")
    if default_sqlite.exists():
        console.print(f"Found Zotero at {default_zotero}")
        use_default = Confirm.ask("Use this?", default=True)
        if use_default:
            return ZoteroConfig(
                enabled=True,
                sqlite_path=default_sqlite,
                storage_path=default_storage,
            )
    else:
        console.print(f"No Zotero found at default location ({default_zotero}).")
    skip = Confirm.ask("Skip Zotero?", default=False)
    if skip:
        return ZoteroConfig(
            enabled=False,
            sqlite_path=default_sqlite,
            storage_path=default_storage,
        )
    sqlite_path_str = Prompt.ask("Path to zotero.sqlite", default=str(default_sqlite))
    storage_path_str = Prompt.ask(
        "Path to Zotero storage/ dir", default=str(default_storage)
    )
    return ZoteroConfig(
        enabled=True,
        sqlite_path=Path(sqlite_path_str).expanduser().resolve(),
        storage_path=Path(storage_path_str).expanduser().resolve(),
    )


def _print_mcp_integration_snippet() -> None:
    console.print("[bold]To use from Claude Code / Claude Desktop:[/bold]")
    console.print("Add this snippet to your MCP client settings:\n")
    snippet = """{
  "mcpServers": {
    "partial-recall": {
      "command": "partial-recall",
      "args": ["serve"]
    }
  }
}"""
    console.print(f"[cyan]{snippet}[/cyan]\n")
    console.print(
        "Then run [bold]partial-recall index[/bold] to build your vector index."
    )
