"""First-run wizard: `partial-recall init`.

Walks the user through a hardware-aware, corpus-language-aware embedding model
ladder, vector DB location (with external-volume warning), Zotero auto-detect,
optional folder source, and MCP integration snippet. Writes config.toml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
from partial_recall.hardware import HardwareProfile, detect_hardware
from partial_recall.paths import (
    config_path,
    default_vector_db_path,
)

console = Console()

LanguageGroup = Literal["latin", "south_asian", "arabic_persian", "mixed"]


# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelOption:
    display_name: str
    description: str
    detail: str
    provider: EmbeddingProviderName
    model: str
    ram_required_gb: float
    strong_for: frozenset[str]           # language groups this covers well
    requires_install: str | None         # extra package user must inject
    tier_recommended: tuple[str, ...]    # hardware tiers where this is top pick
    not_recommended_warning: str | None  # shown if picked against advice
    # Provenance — shown so scholars can make an informed choice
    maintainer: str = ""       # institution / corporation name
    hq_country: str = ""       # where the company/institution is headquartered
    open_weights: bool = True  # True = weights are freely downloadable + auditable
    weights_license: str = ""  # e.g. "Apache 2.0", "CC BY 4.0", "proprietary API"
    data_local: bool = True          # True = inference is local; False = data sent to API
    military_contracts: str = ""     # documented defence/military contracts (or "none known")


# Keep this ordered: best-for-corpus first (BGE-M3), then LaBSE, then e5 family,
# then Gemini. The init wizard selects + reorders per context; this order is the
# fallback for the "advanced" free-text path.
_CATALOGUE: tuple[ModelOption, ...] = (
    ModelOption(
        display_name="sentence-transformer · BAAI/bge-m3",
        description="100+ languages · highest local quality",
        detail=(
            "1024-dim · ~580 MB (int8) · ~3.5 GB RAM peak\n"
            "        Best cross-lingual retrieval across all scripts per model documentation.\n"
            "        Language coverage is per BAAI's benchmarks; not independently\n"
            "        verified by partial-recall across all scripts.\n"
            "        CUDA/Metal-accelerated automatically if available."
        ),
        provider="sentence-transformer",
        model="BAAI/bge-m3",
        ram_required_gb=3.5,
        strong_for=frozenset({"latin", "south_asian", "arabic_persian", "mixed"}),
        requires_install="sentence-transformers",
        tier_recommended=("powerful",),
        not_recommended_warning=(
            "BGE-M3 needs ~3.5 GB RAM. On a machine with less than 6 GB "
            "this may crash mid-index. That risk is yours."
        ),
        maintainer="Beijing Academy of AI (BAAI)",
        hq_country="China",
        open_weights=True,
        weights_license="Apache 2.0",
        data_local=True,
        military_contracts=(
            "BAAI is a Chinese state-linked research institution. "
            "No documented commercial military contracts. "
            "If your research is sensitive to Chinese state interests "
            "(Xinjiang, Tibet, Uyghur studies, Hong Kong, Taiwan), "
            "consider LaBSE instead."
        ),
    ),
    ModelOption(
        display_name="sentence-transformer · LaBSE",
        description="109 languages · best coverage of South Asian + Arabic scripts",
        detail=(
            "768-dim · ~550 MB download · ~2.5 GB RAM peak\n"
            "        Designed for Tamil, Malayalam, Bengali, Urdu (Arabic script),\n"
            "        Hindi, Kannada, Telugu, Sinhala, Persian, Swahili.\n"
            "        Coverage per Google Research benchmarks; retrieval quality\n"
            "        across these scripts is not yet independently verified by\n"
            "        partial-recall. Weights run locally — your documents never\n"
            "        leave your machine."
        ),
        provider="sentence-transformer",
        model="sentence-transformers/LaBSE",
        ram_required_gb=2.5,
        strong_for=frozenset({"south_asian", "arabic_persian", "latin", "mixed"}),
        requires_install="sentence-transformers",
        tier_recommended=("standard", "powerful"),
        not_recommended_warning=None,
        maintainer="Google Research (open weights, community-maintained on HuggingFace)",
        hq_country="USA",
        open_weights=True,
        weights_license="Apache 2.0",
        data_local=True,
        military_contracts=(
            "Google (parent company Alphabet) holds Project Nimbus — "
            "a US$1.2B cloud contract with the Israeli government and military (2021). "
            "Google fired employees who protested this contract (2024). "
            "LaBSE weights are open and run locally; no data reaches Google during indexing."
        ),
    ),
    ModelOption(
        display_name="sentence-transformer · intfloat/multilingual-e5-large",
        description="50 languages · higher quality than e5-small · Latin focus",
        detail=(
            "768-dim · ~1.2 GB download · ~2 GB RAM peak\n"
            "        Better than e5-small for European academic prose.\n"
            "        Indic/Arabic coverage is limited — use LaBSE instead."
        ),
        provider="sentence-transformer",
        model="intfloat/multilingual-e5-large",
        ram_required_gb=2.0,
        strong_for=frozenset({"latin"}),
        requires_install="sentence-transformers",
        tier_recommended=("standard", "powerful"),
        not_recommended_warning=(
            "e5-large has poor Tamil, Urdu, and Bengali coverage. "
            "For South Asian corpora, LaBSE or BGE-M3 will recall much more."
        ),
        maintainer="Microsoft Research (intfloat team)",
        hq_country="USA",
        open_weights=True,
        weights_license="MIT",
        data_local=True,
        military_contracts=(
            "Microsoft holds significant US Department of Defense contracts "
            "including JEDI and IVAS (HoloLens for the US Army). "
            "Weights run locally; no data reaches Microsoft during indexing."
        ),
    ),
    ModelOption(
        display_name="local-onnx · intfloat/multilingual-e5-small",
        description="50 languages · safe minimum · works on 4 GB RAM · no extras",
        detail=(
            "384-dim · ~470 MB download · ~1 GB RAM peak\n"
            "        Latin-script strong. Urdu partial. Tamil and Bengali weak.\n"
            "        No extra package needed — works out of the box."
        ),
        provider="local-onnx",
        model="intfloat/multilingual-e5-small",
        ram_required_gb=1.0,
        strong_for=frozenset({"latin"}),
        requires_install=None,
        tier_recommended=("minimal",),
        not_recommended_warning=None,
        maintainer="Microsoft Research (intfloat team)",
        hq_country="USA",
        open_weights=True,
        weights_license="MIT",
        data_local=True,
        military_contracts=(
            "Microsoft holds significant US Department of Defense contracts "
            "including JEDI and IVAS (HoloLens for the US Army). "
            "Weights run locally; no data reaches Microsoft during indexing."
        ),
    ),
    ModelOption(
        display_name="gemini · gemini-embedding-001",
        description="cloud API · excellent multilingual quality · requires internet",
        detail=(
            "No local download · every document sent to Google's US servers.\n"
            "        Requires a Google Cloud account + PARTIAL_RECALL_GEMINI_API_KEY.\n"
            "        Best quality available — at the cost of data sovereignty."
        ),
        provider="gemini",
        model="gemini-embedding-001",
        ram_required_gb=0.0,
        strong_for=frozenset({"latin", "south_asian", "arabic_persian", "mixed"}),
        requires_install=None,
        tier_recommended=(),
        not_recommended_warning=None,
        maintainer="Google (Alphabet Inc.)",
        hq_country="USA",
        open_weights=False,
        weights_license="proprietary cloud API",
        data_local=False,
        military_contracts=(
            "Google holds Project Nimbus — a US$1.2B cloud contract with the "
            "Israeli government and military (2021). Google fired employees who "
            "protested this contract (2024). Every document you index via Gemini "
            "is transmitted to and processed on Google's servers. "
            "Not appropriate for sensitive, unpublished, or politically exposed research."
        ),
    ),
)

# The "custom model name" sentinel — always appears as the last option.
_CUSTOM_OPTION_LABEL = "Enter a model name manually (advanced)"


# ---------------------------------------------------------------------------
# PROVIDER_PROFILES is kept for backwards compat with existing tests that
# monkeypatch it. New code uses _CATALOGUE + _guide_embedding_choice().
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderProfile:
    label: str
    description: str
    provider: EmbeddingProviderName
    model: str
    enabled: bool = True


PROVIDER_PROFILES: tuple[ProviderProfile, ...] = tuple(
    ProviderProfile(
        label=opt.display_name,
        description=opt.description,
        provider=opt.provider,
        model=opt.model,
    )
    for opt in _CATALOGUE
)


# ---------------------------------------------------------------------------
# Init wizard
# ---------------------------------------------------------------------------

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
        "[yellow bold]PRE-RELEASE SOFTWARE — USE AT YOUR OWN RISK[/yellow bold]\n"
        "[dim]partial-recall is under active development and has not been released "
        "for general use.\n"
        "It may lose data, corrupt indices, or behave unexpectedly. "
        "Back up your research materials\n"
        "before indexing. This software is provided as-is, without warranty of any "
        "kind (see AGPL-3.0).\n"
        "CommonerLLP and contributors accept no liability for any loss or damage "
        "arising from use.[/dim]\n"
    )
    console.print(
        "This tool runs entirely on your machine by default. No data leaves your "
        "laptop unless you explicitly choose a cloud embedding provider.\n"
    )

    # 1. Embedding provider — hardware-aware, language-aware ladder
    provider_name, model_name = _guide_embedding_choice()

    # 2. Vector DB location
    vector_db_path = _ask_vector_db_path(
        allow_external_volume=allow_external_volume
    )

    # 3. Zotero auto-detect
    zotero_cfg = _ask_zotero()

    # 4. Folder (skipped in init wizard — user configures via config.toml)
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

    # 6. Post-install note if sentence-transformers needed
    _print_sentence_transformers_note(provider_name)

    # 7. MCP client integration snippet
    _print_mcp_integration_snippet()


# ---------------------------------------------------------------------------
# Embedding choice — the ladder
# ---------------------------------------------------------------------------

def _guide_embedding_choice() -> tuple[EmbeddingProviderName, str]:
    """Interactive dialogue that returns (provider_name, model_name).

    Detects hardware, asks about corpus languages, then presents a ranked
    ladder of model options calibrated to both.
    """
    hw = detect_hardware()
    _print_hardware_banner(hw)

    lang = _ask_language_group()
    options = _ranked_options(hw, lang)

    return _ask_model_from_ladder(hw, lang, options)


def _print_hardware_banner(hw: HardwareProfile) -> None:
    parts = [hw.ram_label()]
    if hw.chip_label():
        parts.append(hw.chip_label())
    console.print(f"[dim]Detected: {' · '.join(parts)}[/dim]\n")


def _ask_language_group() -> LanguageGroup:
    console.print(
        "[bold]What languages and scripts are in your research materials?[/bold]"
    )
    console.print(
        "[dim](This helps us recommend the right embedding model for your corpus.)"
        "[/dim]\n"
    )
    console.print(
        "  1) Latin-script only — English, French, German, Spanish, Portuguese, Italian..."
    )
    console.print(
        "  2) South Asian scripts — Tamil, Malayalam, Bengali, Urdu, Hindi, Kannada, Telugu..."
    )
    console.print(
        "  3) Arabic, Persian, or other Arabic-script languages "
        "(including Urdu primarily in Arabic script)"
    )
    console.print(
        "  4) Mixed — two or more of the above, or scripts not listed "
        "(common in area-studies research)\n"
    )

    mapping: dict[int, LanguageGroup] = {
        1: "latin", 2: "south_asian", 3: "arabic_persian", 4: "mixed"
    }
    choice = IntPrompt.ask(
        "Your corpus languages", default=1, choices=["1", "2", "3", "4"]
    )
    return mapping[choice]


def _ranked_options(hw: HardwareProfile, lang: LanguageGroup) -> list[ModelOption]:
    """Return catalogue options sorted: recommended for this context first."""
    fits = [o for o in _CATALOGUE if o.ram_required_gb <= (hw.ram_gb or 99)]
    wont_fit = [o for o in _CATALOGUE if o.ram_required_gb > (hw.ram_gb or 99)]

    def _score(opt: ModelOption) -> int:
        score = 0
        if hw.tier in opt.tier_recommended:
            score += 10
        if lang in opt.strong_for or "mixed" in opt.strong_for:
            score += 5
        if lang == "south_asian" and lang in opt.strong_for:
            score += 3
        if hw.is_apple_silicon and opt.model == "BAAI/bge-m3":
            score += 2  # Metal acceleration makes this a real win on M-series
        return score

    ranked = sorted(fits, key=_score, reverse=True) + wont_fit
    return ranked


def _ask_model_from_ladder(
    hw: HardwareProfile,
    lang: LanguageGroup,
    options: list[ModelOption],
) -> tuple[EmbeddingProviderName, str]:
    lang_label = {
        "latin": "Latin-script",
        "south_asian": "South Asian scripts",
        "arabic_persian": "Arabic/Persian scripts",
        "mixed": "mixed / multilingual",
    }[lang]

    console.print(
        f"\n[bold]Embedding model options[/bold] "
        f"— based on your machine ({hw.ram_label()}) and corpus ({lang_label}):\n"
    )
    console.print(
        "[dim]  These are suggestions, not guarantees. partial-recall has not been "
        "stress-tested\n"
        "  on every machine, corpus size, or model combination in the wild. The RAM "
        "estimates\n"
        "  are approximate — your actual usage will vary. The risks are real and we "
        "want you\n"
        "  to know them before deciding. If something breaks, file an issue.[/dim]\n"
    )

    if lang in ("south_asian", "arabic_persian", "mixed"):
        console.print(
            "[dim]  Note: the default multilingual-e5-small has limited coverage of "
            "Tamil, Urdu, Bengali, Malayalam, and Arabic script.\n"
            "  The models below are ranked by fit for your corpus.[/dim]\n"
        )

    # Show the ranked list. Gemini always last; custom always last+1.
    # Options that won't fit RAM are shown last with a warning.
    fits_ram = [o for o in options if o.ram_required_gb <= (hw.ram_gb or 99)]
    wont_fit = [o for o in options if o.ram_required_gb > (hw.ram_gb or 99)]

    displayed: list[ModelOption] = []
    idx = 1
    for i, opt in enumerate(fits_ram):
        marker = " [bold green]← recommended[/bold green]" if i == 0 else ""
        console.print(f"  [bold]{idx})[/bold] {opt.display_name}{marker}")
        console.print(f"       {opt.description}")
        console.print(f"       [dim]{opt.detail}[/dim]")
        if opt.maintainer:
            country = f" · HQ: {opt.hq_country}" if opt.hq_country else ""
            console.print(f"       [dim]By: {opt.maintainer}{country}[/dim]")
        if opt.weights_license:
            ow = "open weights" if opt.open_weights else "proprietary"
            console.print(
                f"       [dim]License: {opt.weights_license} ({ow})[/dim]"
            )
        if not opt.data_local:
            console.print(
                "       [yellow]⚠ Data sovereignty: "
                "your documents leave your machine[/yellow]"
            )
        if opt.military_contracts:
            console.print(
                f"       [dim]Defence/military contracts: {opt.military_contracts}[/dim]"
            )
        if opt.requires_install:
            console.print(
                f"       [dim]Needs: pipx inject partial-recall {opt.requires_install}[/dim]"
            )
        console.print()
        displayed.append(opt)
        idx += 1

    if wont_fit:
        console.print(
            f"  [dim]The following require more RAM than your machine has ({hw.ram_label()}):[/dim]"
        )
        for opt in wont_fit:
            console.print(
                f"  [dim]{idx}) {opt.display_name} — needs ~{opt.ram_required_gb:.0f} GB RAM[/dim]"
            )
            displayed.append(opt)
            idx += 1
        console.print()

    console.print(f"  {idx}) {_CUSTOM_OPTION_LABEL}\n")
    custom_idx = idx

    valid = list(range(1, idx + 1))
    choice = IntPrompt.ask(
        "Choose (Enter for recommended)",
        default=1,
        choices=[str(v) for v in valid],
    )

    if choice == custom_idx:
        return _ask_custom_model()

    selected = displayed[choice - 1]

    # Warn if picked against recommendation (not in RAM-fits + not top scorer)
    if choice != 1 and selected.not_recommended_warning:
        console.print(f"\n[yellow]Note: {selected.not_recommended_warning}[/yellow]")
        if not Confirm.ask("Continue with this choice?", default=True):
            return _ask_model_from_ladder(hw, lang, options)

    # Warn if user picked a model that won't fit RAM
    if selected in wont_fit:
        console.print(
            f"\n[yellow]Warning: {selected.display_name} needs "
            f"~{selected.ram_required_gb:.0f} GB RAM. "
            f"Your machine has {hw.ram_label()}. "
            "We do not know how this will behave on your machine. "
            "That risk is yours.[/yellow]"
        )
        if not Confirm.ask("Continue anyway?", default=False):
            return _ask_model_from_ladder(hw, lang, options)

    return selected.provider, selected.model


def _ask_custom_model() -> tuple[EmbeddingProviderName, str]:
    console.print(
        "\n[dim]You can use any HuggingFace sentence-transformers model.[/dim]"
    )
    console.print(
        "[dim]For local-onnx, only intfloat/ multilingual-e5-* models are tested."
        "[/dim]\n"
    )
    provider_choice = IntPrompt.ask(
        "Provider: 1=local-onnx  2=sentence-transformer  3=gemini",
        default=2,
        choices=["1", "2", "3"],
    )
    provider_map: dict[int, EmbeddingProviderName] = {
        1: "local-onnx", 2: "sentence-transformer", 3: "gemini"
    }
    provider = provider_map[provider_choice]
    model = Prompt.ask(
        "Model name (HuggingFace ID)",
        default="intfloat/multilingual-e5-small",
    )
    return provider, model


# ---------------------------------------------------------------------------
# Remaining wizard steps
# ---------------------------------------------------------------------------

def _ask_provider_profile() -> ProviderProfile:
    """Legacy entry point kept for tests that monkeypatch PROVIDER_PROFILES."""
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
                f"[yellow]Option {choice} is not yet available. "
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
            "   On macOS this can cause sandbox / sleep-throttling issues.[/yellow]"
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


def _print_sentence_transformers_note(provider: EmbeddingProviderName) -> None:
    if provider != "sentence-transformer":
        return
    console.print(
        "[bold]One extra step:[/bold] the model you chose needs the "
        "[cyan]sentence-transformers[/cyan] package.\n"
        "Install it with:\n\n"
        "    [cyan]pipx inject partial-recall sentence-transformers[/cyan]\n\n"
        "Then run [bold]partial-recall index[/bold] to download the model and build your index.\n"
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
