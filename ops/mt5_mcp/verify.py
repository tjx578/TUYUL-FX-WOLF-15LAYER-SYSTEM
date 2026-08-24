"""Sanitized live verifier for the Native MT5 read-only MCP server."""

from __future__ import annotations

import asyncio
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from ops.mt5_mcp.server import ALLOWED_TOOL_NAMES, mcp


def _payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for content in getattr(result, "content", []):
        text = getattr(content, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


async def _verify_client(client: Any) -> dict[str, Any]:
    listing = await client.list_tools()
    names = sorted(tool.name for tool in listing.tools)
    expected = sorted(ALLOWED_TOOL_NAMES)
    measurements: dict[str, Any] = {}
    for name in expected:
        arguments = {"limit": 1} if name.startswith("mt5_history_") else {}
        result = await client.call_tool(name, arguments)
        payload = _payload(result)
        measurements[name] = {
            "measurement_state": payload.get("measurement_state", "NOT_MEASURED"),
            "record_count": payload.get("record_count"),
            "source_record_count": payload.get("source_record_count"),
            "truncated": payload.get("truncated"),
            "error_code": payload.get("error_code"),
        }

    measured_states = {"MEASURED", "MEASURED_EMPTY"}
    all_measured = all(item["measurement_state"] in measured_states for item in measurements.values())
    return {
        "schema_version": "wolf15.native-mt5-mcp-verification.v1",
        "tool_surface_exact": names == expected,
        "tool_names": names,
        "write_tool_count": 0 if names == expected else "NOT_MEASURED",
        "all_live_reads_measured": all_measured,
        "measurements": measurements,
        "DIRECT_BROKER_STATE": "MEASURED" if all_measured else "NOT_MEASURED",
        "BROKER_RECONCILIATION": "NOT_EXECUTED",
    }


async def verify() -> dict[str, Any]:
    async with Client(mcp) as client:
        return await _verify_client(client)


async def verify_configured_stdio(config_path: Path) -> dict[str, Any]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    entry = config["mcp_servers"]["native_mt5_readonly"]
    parameters = StdioServerParameters(
        command=entry["command"],
        args=entry.get("args", []),
        env=entry.get("env", {}),
        cwd=entry.get("cwd"),
    )
    async with Client(stdio_client(parameters)) as client:
        return await _verify_client(client)


def main() -> int:
    stdio_mode = "--stdio" in sys.argv[1:]
    config_path = Path.home() / ".codex" / "config.toml"
    report = asyncio.run(verify_configured_stdio(config_path) if stdio_mode else verify())
    report["transport"] = "configured_stdio" if stdio_mode else "in_process"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["tool_surface_exact"] and report["all_live_reads_measured"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
