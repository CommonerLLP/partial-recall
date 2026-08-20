"""The Tool input-schema read must work on mcp 1.x and on mcp 2.x.

mcp 2.0.0 renamed `Tool.inputSchema` to `Tool.input_schema` and kept the
old name only as a serialisation alias. Eight schema tests broke on that
rename. `tool_input_schema` is the single read point that absorbs it.
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from partial_recall.mcp.compat import tool_input_schema

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


class _OneXTool:
    """Stands in for mcp 1.x, which has no `input_schema` attribute."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.inputSchema = schema  # noqa: N803


def test_reads_the_schema_off_a_real_tool() -> None:
    tool = Tool(name="t", description="d", inputSchema=SCHEMA)
    assert tool_input_schema(tool) == SCHEMA


def test_reads_the_schema_off_a_1x_style_tool() -> None:
    assert tool_input_schema(_OneXTool(SCHEMA)) == SCHEMA  # type: ignore[arg-type]


def test_every_shipped_tool_exposes_an_object_schema() -> None:
    from partial_recall.mcp.server import ALL_TOOLS

    assert ALL_TOOLS
    for tool in ALL_TOOLS:
        schema = tool_input_schema(tool)
        assert schema["type"] == "object", tool.name
