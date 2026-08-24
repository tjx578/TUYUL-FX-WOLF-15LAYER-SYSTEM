"""Native MT5 read-only MCP integration."""

from __future__ import annotations

from typing import Any

__all__ = ["ALLOWED_TOOL_NAMES", "MT5ReadOnlyBridge", "mcp"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from ops.mt5_mcp import server

    return getattr(server, name)
