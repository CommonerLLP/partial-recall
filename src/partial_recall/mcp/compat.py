"""Version differences between mcp SDK 1.x and 2.x.

mcp 1.x names the Tool input-schema field `inputSchema`. mcp 2.0.0
renamed the field to `input_schema` and kept `inputSchema` only as a
serialisation alias, so attribute reads of `tool.inputSchema` raise
AttributeError on 2.x.

Construction is not affected. `Tool(inputSchema=...)` works on both,
because 2.x validates by alias. Only reads need this helper.
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool


def tool_input_schema(tool: Tool) -> dict[str, Any]:
    """Return a Tool's input schema on either mcp 1.x or 2.x."""
    if hasattr(tool, "input_schema"):
        return tool.input_schema
    return tool.inputSchema  # type: ignore[attr-defined,no-any-return]
