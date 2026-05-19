"""`partial-recall keyring` — store / read / delete secrets in the OS keyring.

Wraps `partial_recall.secrets` so a user can do:

    partial-recall keyring set-gemini    # prompts (hidden input) and stores
    partial-recall keyring status        # is a key set? which backend?
    partial-recall keyring delete-gemini # removes the stored key

Backed by:
  - macOS    → Keychain
  - Linux    → Secret Service (Gnome Keyring / KWallet)
  - Windows  → Credential Manager

Requires the `keyring` optional dependency:
    pipx inject partial-recall keyring
"""

from __future__ import annotations

import typer
from rich.console import Console

from partial_recall.errors import PartialRecallError
from partial_recall.secrets import (
    SERVICE_NAME,
    delete_gemini_api_key,
    get_gemini_api_key,
    keyring_available,
    set_gemini_api_key,
)

console = Console()

app = typer.Typer(
    name="keyring",
    help="Store / read / delete secrets in the OS keyring.",
    no_args_is_help=True,
)


def _require_keyring() -> None:
    if not keyring_available():
        raise PartialRecallError(
            "The `keyring` package is not installed or no working "
            "backend is configured on this machine. Install it with "
            "`pipx inject partial-recall keyring` (recommended) or "
            "`pip install 'partial-recall[keyring]'`."
        )


@app.command("status")
def status_command() -> None:
    """Report whether a Gemini API key is stored in the OS keyring."""
    if not keyring_available():
        console.print(
            "[yellow]keyring not available[/yellow] — the `keyring` "
            "package is missing or no backend is configured. Install "
            "with `pipx inject partial-recall keyring`."
        )
        raise typer.Exit(code=1)

    import keyring as kr
    backend = kr.get_keyring()
    backend_name = type(backend).__module__ + "." + type(backend).__name__
    console.print(f"[bold]Backend:[/bold] {backend_name}")
    console.print(f"[bold]Service:[/bold] {SERVICE_NAME}")

    key = get_gemini_api_key()
    if key:
        # Show only a short prefix — never the full key.
        masked = key[:6] + "…" + key[-2:] if len(key) > 10 else "***"
        console.print(
            f"[green]✓[/green] Gemini API key stored (length {len(key)}): {masked}"
        )
    else:
        console.print(
            "[yellow]·[/yellow] No Gemini API key stored. Set it with "
            "`partial-recall keyring set-gemini`."
        )


@app.command("set-gemini")
def set_gemini_command(
    value: str = typer.Option(  # noqa: B008
        None,
        "--value",
        help="API key value. If omitted, you'll be prompted (hidden input).",
    ),
) -> None:
    """Store a Gemini API key in the OS keyring."""
    _require_keyring()
    console.print(
        "[dim]partial-recall will store your Gemini API key in your "
        "system keychain (macOS Keychain / Linux Secret Service / "
        "Windows Credential Manager). This keeps the key out of config "
        "files and environment variables where it could leak.[/dim]"
    )
    console.print(
        "[dim]If macOS shows a Keychain access dialog, that is "
        "partial-recall — not Python — requesting permission to save "
        "your key securely.[/dim]"
    )
    if value is None:
        value = typer.prompt("Paste your Gemini API key", hide_input=True).strip()
    if not value:
        raise PartialRecallError("API key cannot be empty.")
    set_gemini_api_key(value)
    console.print(
        "[green]✓[/green] Gemini API key saved to system keychain. "
        "partial-recall will read it automatically from now on — no "
        "environment variable needed."
    )


@app.command("delete-gemini")
def delete_gemini_command() -> None:
    """Remove the stored Gemini API key from the OS keyring."""
    _require_keyring()
    delete_gemini_api_key()
    console.print(
        f"[green]✓[/green] Removed Gemini API key from keyring "
        f"(service={SERVICE_NAME})."
    )
