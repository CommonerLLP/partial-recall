"""Typer app for partial-recall.

Global flags applied via Typer callback. Subcommands attached from
sibling modules.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from partial_recall import __version__
from partial_recall.cli.doctor import doctor_command
from partial_recall.cli.import_cookjohn import import_app
from partial_recall.cli.index import index_command
from partial_recall.cli.init import init_command
from partial_recall.cli.keyring_cmd import app as keyring_app
from partial_recall.cli.place import place_command
from partial_recall.cli.search import search_command
from partial_recall.cli.serve import serve_command
from partial_recall.cli.status import status_command
from partial_recall.errors import PartialRecallError
from partial_recall.logging_setup import configure_logging

app = typer.Typer(
    name="partial-recall",
    help="Semantic memory for your scholarly corpus.",
    no_args_is_help=True,
    add_completion=True,
)

# Register subcommands
app.command(name="init", help="Run the first-run wizard and write config.toml.")(
    init_command
)
app.command(name="index", help="Build / update the vector index.")(index_command)
app.command(name="status", help="Show index status.")(status_command)
app.command(name="place", help="Position a candidate work against the corpus.")(place_command)
app.command(name="search", help="Run a semantic search.")(search_command)
app.command(name="serve", help="Start the MCP server over stdio.")(serve_command)
app.command(
    name="doctor",
    help="Run diagnostic checks — surfaces config / corpus / install issues.",
)(doctor_command)
app.add_typer(import_app, name="import")
app.add_typer(keyring_app, name="keyring")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"partial-recall {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose", "-v", count=True, help="Increase verbosity (-v, -vv)."
        ),
    ] = 0,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress non-error output."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json", help="Emit JSON to stdout instead of human output."
        ),
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = None,
) -> None:
    """partial-recall — semantic memory for your scholarly corpus."""
    # Map flags to log level
    if quiet:
        level = "ERROR"
    elif verbose >= 2:
        level = "DEBUG"
    elif verbose >= 1:
        level = "INFO"
    else:
        level = "WARNING"
    log_format = "json" if json_output else "human"
    configure_logging(level=level, format=log_format)


def cli_entry() -> None:
    """Wrapper that maps PartialRecallError into exit codes + clean messages."""
    try:
        app()
    except PartialRecallError as e:
        typer.echo(f"error: {e}", err=True)
        if e.actionable_hint:
            typer.echo(f"hint: {e.actionable_hint}", err=True)
        sys.exit(e.exit_code)


# Used by __main__.py
__all__ = ["app", "cli_entry"]
