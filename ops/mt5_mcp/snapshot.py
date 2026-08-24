"""Collect one bounded direct-broker snapshot through the configured MCP server.

This module is an internal transport helper for Channel B reconciliation.  It
prints broker observations, but never receives or inherits ``AUDIT_DATABASE_URL``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tomllib
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from ops.mt5_mcp import account_binding
from ops.mt5_mcp.server import ALLOWED_TOOL_NAMES


def _payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for content in getattr(result, "content", []):
        text = getattr(content, "text", None)
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


async def collect(config_path: Path, *, from_utc: str, to_utc: str) -> dict[str, Any]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    entry = config["mcp_servers"]["native_mt5_readonly"]
    configured_tools = tuple(entry.get("enabled_tools", ()))
    server_environment = {
        str(key): str(value)
        for key, value in entry.get("env", {}).items()
        if key not in {account_binding.KEY_ENV, account_binding.KEY_ID_ENV}
    }
    for name in (account_binding.KEY_ENV, account_binding.KEY_ID_ENV):
        value = os.environ.get(name)
        if value is not None:
            server_environment[name] = value
    parameters = StdioServerParameters(
        command=entry["command"],
        args=entry.get("args", []),
        env=server_environment,
        cwd=entry.get("cwd"),
    )
    async with Client(stdio_client(parameters)) as client:
        listing = await client.list_tools()
        listed_tools = tuple(sorted(tool.name for tool in listing.tools))
        snapshots: dict[str, dict[str, Any]] = {}
        for name in ALLOWED_TOOL_NAMES:
            arguments: dict[str, Any] = {}
            if name.startswith("mt5_history_"):
                arguments = {"from_utc": from_utc, "to_utc": to_utc, "limit": 1_000}
            snapshots[name] = _payload(await client.call_tool(name, arguments))

    expected = tuple(sorted(ALLOWED_TOOL_NAMES))
    return {
        "schema_version": "wolf15.native-mt5-reconciliation-snapshot.v2",
        "tool_surface_exact": listed_tools == expected and tuple(sorted(configured_tools)) == expected,
        "tool_names": list(listed_tools),
        "window": {"from_utc": from_utc, "to_utc": to_utc},
        "snapshots": snapshots,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-utc", required=True)
    parser.add_argument("--to-utc", required=True)
    parser.add_argument("--config", type=Path, default=Path.home() / ".codex" / "config.toml")
    args = parser.parse_args()
    report = asyncio.run(collect(args.config, from_utc=args.from_utc, to_utc=args.to_utc))
    print(json.dumps(report, sort_keys=True))
    return 0 if report["tool_surface_exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
