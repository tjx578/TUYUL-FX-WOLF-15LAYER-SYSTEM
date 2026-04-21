#!/usr/bin/env python
"""Focused WS diagnostic probe for follower-lock vs provider/auth/network failures.

Usage:
    python -m scripts.ws_diagnostic_probe
    python -m scripts.ws_diagnostic_probe --symbol EURUSD --tick-wait-sec 20

The probe is additive and read-mostly:
- reads the Redis leader-lock holder, if Redis is reachable
- opens a direct Finnhub WebSocket connection using the active key
- subscribes to one symbol and waits briefly for a trade tick

It does not modify ingest readiness, thresholds, or execution authority.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import time
from typing import Any, cast

import websockets

from config_loader import get_enabled_symbols
from ingest.finnhub_key_manager import finnhub_keys
from ingest.finnhub_ws import FINNHUB_WS_URL, LEADER_LOCK_KEY, FinnhubSymbolMapper
from ingest.redis_setup import connect_redis


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose Finnhub WS connectivity from the current runtime environment."
    )
    parser.add_argument(
        "--symbol", default=None, help="Internal symbol to subscribe, e.g. EURUSD. Defaults to first enabled symbol."
    )
    parser.add_argument("--connect-timeout-sec", type=float, default=15.0, help="WS connect timeout.")
    parser.add_argument(
        "--tick-wait-sec", type=float, default=30.0, help="How long to wait for a trade tick after subscribe."
    )
    return parser.parse_args()


async def _read_leader_lock() -> dict[str, Any]:
    result: dict[str, Any] = {
        "redis_ok": False,
        "leader_lock_holder": None,
        "leader_lock_error": None,
    }
    redis: Any | None = None
    try:
        redis = cast(Any, await connect_redis())
        result["redis_ok"] = True
        assert redis is not None
        holder = await redis.get(LEADER_LOCK_KEY)
        result["leader_lock_holder"] = holder
    except Exception as exc:
        result["leader_lock_error"] = f"{type(exc).__name__}:{exc}"
    finally:
        if redis is not None:
            await redis.aclose()
    return result


def _classify_probe_failure(exc: Exception) -> tuple[str, str | None]:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    if status_code in (401, 403):
        return "auth_failure", f"HTTP {status_code}"
    if status_code == 429:
        return "provider_rate_limit", "HTTP 429"
    if isinstance(exc, ssl.SSLError):
        return "tls_failure", str(exc)
    if isinstance(exc, OSError):
        return "network_failure", str(exc)
    return "provider_or_client_failure", f"{type(exc).__name__}:{exc}"


async def _probe_direct_ws(symbol: str, connect_timeout_sec: float, tick_wait_sec: float) -> dict[str, Any]:
    token = finnhub_keys.current_key()
    if not token:
        return {
            "connected": False,
            "subscribed": False,
            "tick_received": False,
            "failure_kind": "missing_api_key",
            "failure_detail": "No FINNHUB_API_KEY configured",
        }

    external_symbol = FinnhubSymbolMapper("OANDA").register(symbol)
    url = FINNHUB_WS_URL.format(token=token)
    result: dict[str, Any] = {
        "connected": False,
        "subscribed": False,
        "tick_received": False,
        "failure_kind": None,
        "failure_detail": None,
        "symbol": symbol,
        "external_symbol": external_symbol,
        "messages_seen": 0,
        "trade_messages_seen": 0,
        "tick_wait_sec": tick_wait_sec,
    }

    try:
        async with asyncio.timeout(connect_timeout_sec):
            async with websockets.connect(
                url,
                ping_interval=20.0,
                ping_timeout=10.0,
                close_timeout=10.0,
                max_size=10_000_000,
            ) as ws:
                result["connected"] = True
                await ws.send(json.dumps({"type": "subscribe", "symbol": external_symbol}))
                result["subscribed"] = True

                deadline = time.monotonic() + tick_wait_sec
                while time.monotonic() < deadline:
                    remaining = max(0.1, deadline - time.monotonic())
                    raw_msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    result["messages_seen"] += 1
                    message = json.loads(raw_msg)
                    if message.get("type") != "trade":
                        continue
                    result["trade_messages_seen"] += 1
                    trades = message.get("data") or []
                    if not isinstance(trades, list):
                        continue
                    for trade in trades:
                        if not isinstance(trade, dict):
                            continue
                        if trade.get("s") == external_symbol:
                            result["tick_received"] = True
                            result["last_trade_symbol"] = trade.get("s")
                            result["last_trade_ts_ms"] = trade.get("t")
                            result["last_trade_price"] = trade.get("p")
                            return result

                result["failure_kind"] = "connected_but_silent"
                result["failure_detail"] = f"No trade tick for {external_symbol} within {tick_wait_sec:.1f}s"
                return result
    except TimeoutError as exc:
        result["failure_kind"] = "connect_timeout"
        result["failure_detail"] = str(exc)
        return result
    except Exception as exc:
        failure_kind, failure_detail = _classify_probe_failure(exc)
        result["failure_kind"] = failure_kind
        result["failure_detail"] = failure_detail
        return result


def _derive_diagnosis(leader_info: dict[str, Any], ws_probe: dict[str, Any]) -> str:
    local_replica = os.getenv("RAILWAY_REPLICA_ID", "unknown")
    holder = leader_info.get("leader_lock_holder")
    if isinstance(holder, bytes):
        holder = holder.decode()

    if holder and holder != local_replica and ws_probe.get("connected"):
        return "follower_lock_most_likely"
    if holder and holder != local_replica and not ws_probe.get("connected"):
        return "mixed_signal_lock_present_but_provider_probe_fails"

    failure_kind = ws_probe.get("failure_kind")
    if failure_kind in {"auth_failure", "provider_rate_limit", "network_failure", "tls_failure", "connect_timeout"}:
        return str(failure_kind)
    if failure_kind == "connected_but_silent":
        return "provider_connected_but_symbol_silent_or_subscription_invalid"
    if ws_probe.get("tick_received"):
        return "direct_ws_ok_service_side_issue_or_lock_contention"
    return "unknown"


async def main() -> None:
    args = _parse_args()
    symbol = args.symbol or (get_enabled_symbols()[0] if get_enabled_symbols() else "EURUSD")
    leader_info, ws_probe = await asyncio.gather(
        _read_leader_lock(),
        _probe_direct_ws(symbol, args.connect_timeout_sec, args.tick_wait_sec),
    )

    local_replica = os.getenv("RAILWAY_REPLICA_ID", "unknown")
    diagnosis = _derive_diagnosis(leader_info, ws_probe)
    output = {
        "event": "ws_diagnostic_probe",
        "local_replica_id": local_replica,
        "requested_symbol": symbol,
        "leader_lock": leader_info,
        "direct_ws_probe": ws_probe,
        "diagnosis": diagnosis,
        "timestamp": time.time(),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
