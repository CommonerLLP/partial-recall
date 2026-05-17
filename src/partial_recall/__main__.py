"""CLI entry point for partial-recall.

The actual Typer app is constructed in partial_recall.cli.app; this module
exists to satisfy the [project.scripts] entry point in pyproject.toml.
"""

from __future__ import annotations


def main() -> None:
    """Console-script entry point.

    Imports the Typer app lazily so `--version` and `--help` stay fast
    and so import errors in subsystems do not break basic CLI invocation.
    """
    from partial_recall.cli.app import cli_entry
    cli_entry()


if __name__ == "__main__":
    main()
