#!/usr/bin/env python3
"""
TUYUL FX Wolf-15 — Quick Endpoint Smoke Test
Run: python test_endpoints.py http://localhost:8000
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else "test-token"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}


async def check(client: httpx.AsyncClient, method: str, path: str, body: dict | None = None) -> None:
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = await client.get(url, headers=HEADERS)
        else:
            r = await client.post(url, json=body or {}, headers=HEADERS)

        icon = "✅" if r.status_code < 400 else "❌"
        print(f"{icon}  {method:4} {path:55} → {r.status_code}")
    except Exception as exc:
        print(f"💥  {method:4} {path:55} → ERROR: {exc}")


async def main() -> None:
    print("\n🐺 TUYUL FX Wolf-15 — Endpoint Smoke Test")
    print(f"   Target: {BASE}")
    print(f"   Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # ── Health (no auth needed) ──
        await check(client, "GET", "/health")

        # ── Phase 0 Bug-Fix Routes ──
        print("\n── BUG-FIX: Trade Write Routes ──")
        await check(client, "GET", "/api/v1/trades/active")
        await check(
            client, "POST", "/api/v1/trades/skip", {"signal_id": "test-001", "pair": "XAUUSD", "reason": "test"}
        )

        # ── Phase 1: New Endpoints ──
        print("\n── NEW: Constitutional Health ──")
        await check(client, "GET", "/api/v1/health/constitutional")
        await check(client, "GET", "/api/v1/equity/history")
        await check(client, "GET", "/api/v1/equity/history?period=1d")

        print("\n── NEW: Risk Events ──")
        await check(client, "GET", "/api/v1/risk/events")
        await check(client, "GET", "/api/v1/risk/events?impact_type=TRADE_BLOCKED")
        await check(client, "GET", "/api/v1/risk/test-account/snapshot")

        print("\n── NEW: Risk Calculate Preview ──")
        await check(
            client,
            "POST",
            "/api/v1/risk/calculate",
            {
                "account_id": "test-account",
                "pair": "XAUUSD",
                "direction": "BUY",
                "entry": 2350.0,
                "sl": 2340.0,
                "tp": 2380.0,
                "risk_percent": 1.0,
            },
        )

        print("\n── NEW: Journal Extended ──")
        await check(client, "GET", "/api/v1/journal/today")
        await check(client, "GET", "/api/v1/journal/weekly")
        await check(client, "GET", "/api/v1/journal/metrics")
        await check(client, "GET", "/api/v1/journal/search?pair=XAUUSD&outcome=WIN")
        await check(client, "GET", "/api/v1/journal/search?journal_type=J2")

        print("\n── NEW: Market Instruments ──")
        await check(client, "GET", "/api/v1/instruments")
        await check(client, "GET", "/api/v1/instruments/XAUUSD")
        await check(client, "GET", "/api/v1/instruments/EURUSD/regime")
        await check(client, "GET", "/api/v1/instruments/GBPUSD/sessions")

        print("\n── NEW: Economic Calendar ──")
        await check(client, "GET", "/api/v1/calendar")
        await check(client, "GET", "/api/v1/calendar?impact=HIGH")
        await check(client, "GET", "/api/v1/calendar/upcoming")
        await check(client, "GET", "/api/v1/calendar/upcoming?hours=2")
        await check(client, "GET", "/api/v1/calendar/news-lock/status")
        await check(
            client, "POST", "/api/v1/calendar/news-lock/enable", {"reason": "NFP Release", "duration_minutes": 30}
        )
        await check(client, "POST", "/api/v1/calendar/news-lock/disable")

        print("\n── Dev: Endpoint Summary ──")
        await check(client, "GET", "/api/v1/endpoints")

    print("\n" + "─" * 80)
    print("Done. Fix any ❌ before deploying to Railway.")


if __name__ == "__main__":
    asyncio.run(main())
