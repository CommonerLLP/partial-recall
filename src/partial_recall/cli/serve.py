"""`partial-recall serve` — start the MCP server (stdio transport)."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from pathlib import Path

import typer
from rich.console import Console

from partial_recall.config.loader import load_config
from partial_recall.config.models import EmbeddingProviderName, PartialRecallConfig
from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.errors import (
    ConfigError,
    IndexNotReadyError,
    PartialRecallError,
)
from partial_recall.mcp.server import run_stdio
from partial_recall.paths import config_path
from partial_recall.store.vector_store import VectorStore

# IMPORTANT: For stdio MCP transport, anything we print to stdout
# becomes protocol-level garbage. ALL human messages must go to stderr.
console = Console(stderr=True)


def _build_provider(
    provider_name: EmbeddingProviderName, model: str, device: str = "auto"
) -> EmbeddingProvider:
    if provider_name == "local-onnx":
        from partial_recall.embedding.providers.local_onnx import LocalONNXProvider

        return LocalONNXProvider(model_name=model)
    if provider_name == "gemini":
        from partial_recall.embedding.providers.gemini import GeminiAPIProvider

        return GeminiAPIProvider(model_name=model)
    if provider_name == "sentence-transformer":
        from partial_recall.embedding.providers.sentence_transformer import (
            SentenceTransformerProvider,
        )

        return SentenceTransformerProvider(model_name=model, device=device)
    raise PartialRecallError(f"Unknown embedding provider: {provider_name}")


def serve_command(
    config: Path = typer.Option(  # noqa: B008
        None,
        "--config",
        help="Path to config.toml (default: platform default).",
    ),
) -> None:
    """Start the MCP server over stdio.

    Typically invoked by an MCP client (Claude Code, Claude Desktop) as a
    subprocess. Stdout is reserved for the MCP protocol; all human output
    (banners, errors, log lines) goes to stderr.
    """
    cfg_path = config if config else config_path()
    if not cfg_path.exists():
        raise ConfigError(
            f"config not found at {cfg_path}; run `partial-recall init` first"
        )
    cfg = load_config(cfg_path)

    if not cfg.index.vector_db_path.exists():
        raise IndexNotReadyError(
            f"Vector DB not found at {cfg.index.vector_db_path}. "
            "Run `partial-recall index` first."
        )

    console.print(
        f"[dim]partial-recall serve — loading provider "
        f"({cfg.embedding.provider}: {cfg.embedding.model})...[/dim]"
    )
    provider = _build_provider(
        cfg.embedding.provider, cfg.embedding.model, cfg.embedding.device
    )
    store = VectorStore(cfg.index.vector_db_path)
    active = store.get_active_run()
    if active is None:
        store.close()
        provider.close()
        raise IndexNotReadyError(
            "No active embedding run in the vector DB. "
            "Run `partial-recall index` first."
        )
    console.print(
        f"[dim]Active run: id={active.run_id}, provider={active.provider}, "
        f"model={active.model_name}, dim={active.dimensions}[/dim]"
    )
    console.print("[dim]MCP server ready on stdio. Awaiting client...[/dim]")

    try:
        asyncio.run(_serve_with_signals(
            store=store, provider=provider, config=cfg,
        ))
    finally:
        store.close()
        provider.close()
        console.print("[dim]MCP server shut down cleanly.[/dim]")


async def _serve_with_signals(
    *,
    store: VectorStore,
    provider: EmbeddingProvider,
    config: PartialRecallConfig,
) -> None:
    """Run the MCP stdio loop; install SIGINT/SIGTERM handlers that signal
    the loop to drain and exit."""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_stop(sig: int) -> None:
        # Schedule the stop without printing to stdout (would corrupt MCP)
        sys.stderr.write(f"[partial-recall] received signal {sig}, draining...\n")
        sys.stderr.flush()
        stop_event.set()

    # SIGINT / SIGTERM. Some platforms (Windows) don't support
    # add_signal_handler in an event loop; fall through to the default
    # SIGINT behaviour (KeyboardInterrupt still terminates the process).
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, _request_stop, sig)

    # Race the MCP loop against the stop event.
    serve_task = asyncio.create_task(
        run_stdio(store=store, provider=provider, config=config)
    )
    stop_task = asyncio.create_task(stop_event.wait())
    _, pending = await asyncio.wait(
        {serve_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    # Cancel whichever didn't finish; let the cancellation propagate cleanly.
    # We drain any pending exception (including CancelledError) so the event
    # loop can shut down without an "unretrieved exception" warning. The
    # signal handler already reported the reason to stderr.
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
