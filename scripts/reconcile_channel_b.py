"""CLI entry point for the bounded Channel B database/broker reconciliation."""

from __future__ import annotations

from pathlib import Path

from ops.mt5_mcp.reconcile import main

if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parents[1]))
