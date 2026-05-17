"""MCP server for partial-recall over stdio.

Uses the lowlevel `mcp.server.Server` API (mcp SDK 1.27.x) with the
`@server.list_tools()` and `@server.call_tool()` decorators. Streams over
stdio via `mcp.server.stdio.stdio_server`.

The store and embedding provider are injected by the caller. Tests build a
Server without ever running the stdio loop; the CLI (T19) wires up a real
store + provider and calls `run_stdio`.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.server.stdio
from mcp.server import Server
from mcp.types import TextContent, Tool

from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.mcp.tools.semantic_search import (
    SEMANTIC_SEARCH_TOOL,
    handle_semantic_search,
)
from partial_recall.store.vector_store import VectorStore


def build_server(
    *,
    store: VectorStore,
    provider: EmbeddingProvider,
) -> Server:
    """Construct a configured MCP Server.

    Tool handlers close over `store` and `provider` via dependency
    injection so tests can pass in fakes without touching globals.
    """
    server: Server = Server("partial-recall")

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list_tools() -> list[Tool]:
        return [SEMANTIC_SEARCH_TOOL]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == SEMANTIC_SEARCH_TOOL.name:
            return await handle_semantic_search(
                arguments or {},
                store=store,
                provider=provider,
            )
        # Unknown tool: return a structured error rather than raising, so
        # the MCP loop survives misrouted requests.
        return [TextContent(
            type="text",
            text=json.dumps(
                {"error": f"Unknown tool: {name}",
                 "hint": "List available tools via the MCP list_tools request."},
                indent=2,
            ),
        )]

    return server


async def run_stdio(
    *,
    store: VectorStore,
    provider: EmbeddingProvider,
) -> None:
    """Run the MCP server over stdio. Blocks until the client disconnects."""
    server = build_server(store=store, provider=provider)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
