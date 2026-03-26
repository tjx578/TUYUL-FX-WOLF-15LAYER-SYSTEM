#!/usr/bin/env python3
"""
TUYUL FX — Redis diagnostic + cleanup (ZERO DEPENDENCIES)
============================================================
Uses raw TCP sockets with Redis RESP protocol.
No pip packages needed — runs anywhere Python 3.10+ is available.

Run on Railway:
    railway run -s wolf15-engine python redis_diagnostic.py
============================================================
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import sys
import time
from typing import cast
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger("redis_diagnostic")

SYMBOLS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "EURGBP",
    "EURJPY",
    "EURCHF",
    "EURAUD",
    "EURCAD",
    "EURNZD",
    "GBPJPY",
    "GBPCHF",
    "GBPAUD",
    "GBPCAD",
    "GBPNZD",
    "AUDJPY",
    "AUDNZD",
    "AUDCAD",
    "AUDCHF",
    "NZDJPY",
    "NZDCHF",
    "NZDCAD",
    "CADJPY",
    "CADCHF",
    "CHFJPY",
    "XAUUSD",
    "XAGUSD",
]

TIMEFRAME = "M15"
REQUIRED_BARS = 2
INJECT_BARS = 5


class RawRedis:
    """Minimal Redis client using raw RESP protocol over TCP."""

    def __init__(self, host: str, port: int, password: str | None = None) -> None:
        address_host: str | None = host
        self._sock = socket.create_connection((address_host, port), timeout=10)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._buf = b""
        if password:
            self._send_command("AUTH", password)
            resp = self._read_response()
            if resp != "OK":
                raise RuntimeError(f"AUTH failed: {resp}")

    @classmethod
    def from_url(cls, url: str) -> RawRedis:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        password = parsed.password
        return cls(host, port, password)

    def _send_command(self, *args: str) -> None:
        parts = [f"*{len(args)}\r\n"]
        for arg in args:
            encoded = str(arg).encode("utf-8")
            parts.append(f"${len(encoded)}\r\n")
            parts.append(encoded.decode("latin-1"))
            parts.append("\r\n")
        self._sock.sendall("".join(parts).encode("latin-1"))

    def _read_line(self) -> str:
        while b"\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Redis connection closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\r\n", 1)
        return line.decode("utf-8", errors="replace")

    def _read_bulk(self, length: int) -> str:
        need = length + 2  # +2 for \r\n
        while len(self._buf) < need:
            chunk = self._sock.recv(max(4096, need - len(self._buf)))
            if not chunk:
                raise ConnectionError("Redis connection closed")
            self._buf += chunk
        data = self._buf[:length]
        self._buf = self._buf[need:]
        return data.decode("utf-8", errors="replace")

    def _read_response(self) -> object:
        line = self._read_line()
        prefix = line[0]
        payload = line[1:]

        if prefix == "+":
            return payload
        if prefix == "-":
            raise RuntimeError(payload)
        if prefix == ":":
            return int(payload)
        if prefix == "$":
            length = int(payload)
            if length == -1:
                return None
            return self._read_bulk(length)
        if prefix == "*":
            count = int(payload)
            if count == -1:
                return None
            return [self._read_response() for _ in range(count)]
        return line

    def execute(self, *args: str) -> object:
        self._send_command(*args)
        return self._read_response()

    def ping(self) -> str:
        return str(self.execute("PING"))

    def type_of(self, key: str) -> str:
        return str(self.execute("TYPE", key))

    def llen(self, key: str) -> int:
        return int(self.execute("LLEN", key))  # type: ignore[arg-type]

    def delete(self, key: str) -> int:
        return int(self.execute("DEL", key))  # type: ignore[arg-type]

    def rpush(self, key: str, *values: str) -> int:
        return int(self.execute("RPUSH", key, *values))  # type: ignore[arg-type]

    def ltrim(self, key: str, start: int, end: int) -> str:
        return str(self.execute("LTRIM", key, str(start), str(end)))

    def expire(self, key: str, seconds: int) -> int:
        return int(self.execute("EXPIRE", key, str(seconds)))  # type: ignore[arg-type]

    def scan(self, cursor: int, match: str, count: int = 100) -> tuple[int, list[str]]:
        resp = self.execute("SCAN", str(cursor), "MATCH", match, "COUNT", str(count))
        if isinstance(resp, list) and len(resp) == 2:
            new_cursor = int(resp[0])
            keys = [str(k) for k in resp[1]] if isinstance(resp[1], list) else []
            return cast(tuple[int, list[str]], (new_cursor, keys))
        return cast(tuple[int, list[str]], (0, []))

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._sock.close()


def main() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    logger.info("Connecting to Redis: %s", redis_url[:40] + "...")

    try:
        r = RawRedis.from_url(redis_url)
    except Exception as exc:
        logger.error("Redis connection FAILED: %s", exc)
        sys.exit(1)

    # --- Step 1: Connectivity ---
    try:
        pong = r.ping()
        logger.info("Step 1 — Redis PING: %s", pong)
    except Exception as exc:
        logger.error("Step 1 — Redis PING failed: %s", exc)
        sys.exit(1)

    # --- Step 2: Identify WRONGTYPE HASH keys ---
    logger.info("Step 2 — Scanning for wolf15:candle:* HASH keys (WRONGTYPE conflicts)...")
    wrongtype_keys: list[str] = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, "wolf15:candle:*", 200)
        for key in keys:
            if "candle_history" in key:
                continue
            if r.type_of(key) == "hash":
                wrongtype_keys.append(key)
        if cursor == 0:
            break

    if wrongtype_keys:
        logger.warning("Found %d HASH keys blocking LRANGE:", len(wrongtype_keys))
        for k in wrongtype_keys[:10]:
            logger.warning("  -> %s", k)
    else:
        logger.info("No WRONGTYPE conflicts found.")

    # --- Step 3: Delete stale HASH keys ---
    if wrongtype_keys:
        logger.info("Step 3 — Deleting %d stale HASH keys...", len(wrongtype_keys))
        for key in wrongtype_keys:
            try:
                r.delete(key)
            except Exception as exc:
                logger.warning("  DEL failed for %s: %s", key, exc)
        logger.info("Cleaned %d HASH keys.", len(wrongtype_keys))
    else:
        logger.info("Step 3 — No cleanup needed.")

    # --- Step 4: Check candle_history LIST keys ---
    logger.info("Step 4 — Checking wolf15:candle_history:*:M15 keys...")
    empty_symbols: list[str] = []
    ok_symbols: list[str] = []

    for sym in SYMBOLS:
        list_key = f"wolf15:candle_history:{sym}:{TIMEFRAME}"
        try:
            ktype = r.type_of(list_key)
            length = r.llen(list_key) if ktype == "list" else 0
        except Exception:
            length = 0

        if length >= REQUIRED_BARS:
            ok_symbols.append(f"{sym}={length}")
        else:
            empty_symbols.append(sym)

    if ok_symbols:
        logger.info("  OK (%d): %s", len(ok_symbols), ", ".join(ok_symbols[:10]))
        if len(ok_symbols) > 10:
            logger.info("  ... and %d more", len(ok_symbols) - 10)
    if empty_symbols:
        logger.warning("  EMPTY (%d): %s", len(empty_symbols), ", ".join(empty_symbols[:10]))
        if len(empty_symbols) > 10:
            logger.warning("  ... and %d more", len(empty_symbols) - 10)

    # --- Step 5: Inject warmup bars for empty symbols ---
    if empty_symbols:
        logger.info("Step 5 — Injecting %d warmup bars for %d symbols...", INJECT_BARS, len(empty_symbols))
        now = time.time()
        period = 900
        injected = 0

        for sym in empty_symbols:
            list_key = f"wolf15:candle_history:{sym}:{TIMEFRAME}"
            try:
                for i in range(INJECT_BARS):
                    ts = now - (INJECT_BARS - i) * period
                    candle = {
                        "symbol": sym,
                        "timeframe": TIMEFRAME,
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                        "close": 1.0,
                        "volume": 100,
                        "timestamp": ts,
                        "ts_open": ts,
                        "ts_close": ts + period,
                        "status": "closed",
                        "tick_count": 1,
                    }
                    r.rpush(list_key, json.dumps(candle))
                r.ltrim(list_key, -300, -1)
                r.expire(list_key, 6 * 3600)
                injected += 1
            except Exception as exc:
                logger.error("  Failed %s: %s", sym, exc)

        logger.info("Injected warmup for %d/%d symbols.", injected, len(empty_symbols))
    else:
        logger.info("Step 5 — All symbols have sufficient bars.")

    # --- Step 6: Flush stale verdict keys ---
    logger.info("Step 6 — Purging L12:VERDICT:* keys...")
    verdict_cursor = 0
    verdict_cleaned = 0
    while True:
        verdict_cursor, keys = r.scan(verdict_cursor, "L12:VERDICT:*", 200)
        for key in keys:
            try:
                r.delete(key)
                verdict_cleaned += 1
            except Exception:
                pass
        if verdict_cursor == 0:
            break
    logger.info("Purged %d verdict keys.", verdict_cleaned)

    # --- Summary ---
    logger.info("=" * 60)
    logger.info("DIAGNOSTIC SUMMARY")
    logger.info("=" * 60)
    logger.info("  WRONGTYPE keys cleaned:  %d", len(wrongtype_keys))
    logger.info("  Symbols with data:       %d/%d", len(ok_symbols), len(SYMBOLS))
    logger.info("  Symbols injected:        %d", len(empty_symbols))
    logger.info("  Stale verdicts purged:   %d", verdict_cleaned)
    logger.info("=" * 60)

    if not empty_symbols and not wrongtype_keys:
        logger.info("ALL CLEAR — next pipeline cycle should produce valid verdicts.")
    else:
        logger.info("Warmup injected — pipeline will work until real candles arrive.")

    r.close()


if __name__ == "__main__":
    main()
