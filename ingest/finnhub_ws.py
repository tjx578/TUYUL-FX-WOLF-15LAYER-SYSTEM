"""
Finnhub Real-time Forex WebSocket Feed

INGESTION ONLY — NO ANALYSIS, NO DECISION.

Finnhub WS protocol:
  - URL: wss://ws.finnhub.io?token=API_KEY
  - Subscribe: {"type": "subscribe", "symbol": "OANDA:EUR_USD"}
  - Tick payload: {"data": [{"p": price, "s": symbol, "t": ts_ms, "v": vol}], "type": "trade"}
"""

from __future__ import annotations

import json
import asyncio
import os
from typing import Any

import websockets
from websockets.exceptions import (
    ConnectionClosedError,
    ConnectionClosedOK,
)
from loguru import logger

from config_loader import load_finnhub, load_pairs
from context.live_context_bus import LiveContextBus


class FinnhubSymbolMapper:
    """
    Bidirectional mapping between internal symbols and Finnhub format.

    Internal : EURUSD, XAUUSD
    Finnhub  : OANDA:EUR_USD, OANDA:XAU_USD
    """

    # Commodity bases that are 3-char but NOT standard currencies
    _COMMODITY_BASES: set[str] = {"XAU", "XAG", "XPT", "XPD"}

    def __init__(self, prefix: str = "OANDA") -> None:
        self._prefix = prefix
        self._to_finnhub: dict[str, str] = {}
        self._to_internal: dict[str, str] = {}

    def register(self, internal_symbol: str) -> str:
        """
        Register an internal symbol and return its Finnhub equivalent.

        Rules:
          - Forex 6-char (EURUSD) → OANDA:EUR_USD
          - Commodity (XAUUSD) → OANDA:XAU_USD
        """
        finnhub_sym = self._convert_to_finnhub(internal_symbol)
        self._to_finnhub[internal_symbol] = finnhub_sym
        self._to_internal[finnhub_sym] = internal_symbol
        return finnhub_sym

    def to_finnhub(self, internal_symbol: str) -> str:
        return self._to_finnhub[internal_symbol]

    def to_internal(self, finnhub_symbol: str) -> str:
        return self._to_internal.get(finnhub_symbol, finnhub_symbol)

    def _convert_to_finnhub(self, sym: str) -> str:
        """EURUSD → OANDA:EUR_USD, XAUUSD → OANDA:XAU_USD."""
        base = sym[:3]
        quote = sym[3:]
        return f"{self._prefix}:{base}_{quote}"


class FinnhubWebSocket:
    """
    Real-time price feed via Finnhub WebSocket.

    Responsibilities:
      1. Connect to wss://ws.finnhub.io
      2. Subscribe to configured forex/commodity pairs
      3. Normalize ticks → push to LiveContextBus
      4. Auto-reconnect with exponential backoff

    NO ANALYSIS. NO DECISION.
    """

    _MAX_RECONNECT_WAIT_SEC: int = 60

    def __init__(self) -> None:
        self._config = load_finnhub()
        self._pairs = load_pairs()
        self._api_key: str = os.getenv("FINNHUB_API_KEY", "")
        self._ws_url: str = self._config["websocket"].get(
            "url", "wss://ws.finnhub.io"
        )
        self._reconnect_interval: int = self._config["websocket"].get(
            "reconnect_interval_sec", 5
        )
        self._ping_interval: int = self._config["websocket"].get(
            "ping_interval_sec", 30
        )
        self._prefix: str = self._config["symbols"].get(
            "symbol_prefix", "OANDA"
        )

        self._mapper = FinnhubSymbolMapper(prefix=self._prefix)
        self._context_bus = LiveContextBus()

        # Pre-register all enabled pairs
        self._finnhub_symbols: list[str] = []
        for pair in self._pairs:
            if pair.get("enabled", True):
                fh_sym = self._mapper.register(pair["symbol"])
                self._finnhub_symbols.append(fh_sym)

        if not self._api_key:
            logger.error(
                "FINNHUB_API_KEY not set — WebSocket will fail to authenticate"
            )

    async def _connect(self) -> websockets.WebSocketClientProtocol: # pyright: ignore[reportAttributeAccessIssue]
        url = f"{self._ws_url}?token={self._api_key}"
        logger.info("Connecting to Finnhub WebSocket...")
        ws = await websockets.connect(
            url,
            ping_interval=self._ping_interval,
            ping_timeout=self._ping_interval + 10,
        )
        logger.info("Finnhub WebSocket connected")
        return ws

    async def _subscribe(
        self, ws: websockets.WebSocketClientProtocol # pyright: ignore[reportAttributeAccessIssue]
    ) -> None:
        for fh_sym in self._finnhub_symbols:
            payload = json.dumps(
                {"type": "subscribe", "symbol": fh_sym}
            )
            await ws.send(payload)
            logger.debug(f"Subscribed: {fh_sym}")

        logger.info(
            f"Subscribed to {len(self._finnhub_symbols)} symbols on Finnhub"
        )

    async def run(self) -> None:
        """Main event loop with exponential-backoff reconnect."""
        backoff: int = self._reconnect_interval

        while True:
            try:
                async with await self._connect() as ws:
                    await self._subscribe(ws)
                    backoff = self._reconnect_interval  # reset on success

                    async for raw_msg in ws:
                        msg = json.loads(raw_msg)
                        await self._handle_message(msg)

            except ConnectionClosedOK:
                logger.info("Finnhub WS closed gracefully")
                break

            except (
                ConnectionClosedError,
                ConnectionError,
                OSError,
            ) as exc:
                logger.warning(
                    f"Finnhub WS connection lost: {exc} — "
                    f"reconnecting in {backoff}s"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._MAX_RECONNECT_WAIT_SEC)

            except Exception as exc:
                logger.error(
                    f"Finnhub WS unexpected error: {exc} — "
                    f"reconnecting in {backoff}s"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._MAX_RECONNECT_WAIT_SEC)

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """
        Parse Finnhub trade message and push normalized ticks.

        Finnhub payload:
        {
            "data": [
                {"p": 1.1842, "s": "OANDA:EUR_USD", "t": 1616682307950, "v": 100}
            ],
            "type": "trade"
        }
        """
        if msg.get("type") != "trade":
            return

        trades: list[dict[str, Any]] = msg.get("data", [])
        for trade in trades:
            finnhub_symbol = trade.get("s", "")
            internal_symbol = self._mapper.to_internal(finnhub_symbol)
            price = trade.get("p")
            timestamp_ms = trade.get("t")

            if not price or not timestamp_ms:
                continue

            tick: dict[str, Any] = {
                "symbol": internal_symbol,
                "bid": price,
                "ask": price,  # Finnhub WS gives last price, not bid/ask
                "timestamp": timestamp_ms / 1000.0,  # ms → seconds
                "source": "finnhub_ws",
            }

            self._context_bus.update_tick(tick)
