#!/usr/bin/env python
"""
Probe Finnhub pairs for premium access requirements.

Usage:
    python -m scripts.probe_finnhub_premium          # probe all enabled pairs
    python -m scripts.probe_finnhub_premium XAUUSD   # probe specific pair(s)

Outputs results to stdout and optionally updates
config/finnhub_premium.yaml.
"""

from __future__ import annotations

import asyncio
import sys

from config_loader import CONFIG
from ingest.finnhub_candles import FinnhubCandleFetcher


async def main(symbols: list[str] | None = None) -> None:
    fetcher = FinnhubCandleFetcher()

    if not symbols:
        symbols = CONFIG["pairs"].get("symbols", [])

    results = await fetcher.probe_premium_pairs(symbols=symbols)

    # Print summary table
    print("\n" + "=" * 50)
    print("Finnhub Premium Probe Results")
    print("=" * 50)
    for symbol in sorted(results):
        status = results[symbol]
        marker = "✓" if status == "free" else "✗" if status == "premium" else "?"
        print(f"  {marker} {symbol:12s} → {status}")
    print("=" * 50)

    free = [s for s, v in results.items() if v == "free"]
    premium = [s for s, v in results.items() if v == "premium"]
    errors = [s for s, v in results.items() if v == "error"]

    print(f"\nFree:    {len(free)}")
    print(f"Premium: {len(premium)}")
    print(f"Errors:  {len(errors)}")

    if premium:
        print(f"\nPremium pairs: {sorted(premium)}")
    if errors:
        print(f"Error pairs:   {sorted(errors)}")


if __name__ == "__main__":
    symbols_arg = sys.argv[1:] if len(sys.argv) > 1 else None
    asyncio.run(main(symbols_arg))
