import os
import json
import asyncio
import websockets
from loguru import logger

from config_loader import load_settings, load_pairs
from context.live_context_bus import LiveContextBus


class TwelveDataWebSocket:
    """
    Realtime price feed via Twelve Data WebSocket
    NO ANALYSIS
    NO DECISION
    """

    def __init__(self):
        self.settings = load_settings()
        self.pairs = load_pairs()
        self.api_key = os.getenv("TWELVE_DATA_API_KEY")
        self.ws_url = os.getenv("TWELVE_DATA_WS_URL")

        self.context_bus = LiveContextBus()

    async def connect(self):
        logger.info("Connecting to Twelve Data WebSocket...")
        return await websockets.connect(self.ws_url)

    async def subscribe(self, ws):
        symbols = ",".join([p["symbol"] for p in self.pairs])
        payload = {
            "action": "subscribe",
            "params": {
                "symbols": symbols,
                "apikey": self.api_key,
            },
        }
        await ws.send(json.dumps(payload))
        logger.info(f"Subscribed to symbols: {symbols}")

    async def run(self):
        while True:
            try:
                async with await self.connect() as ws:
                    await self.subscribe(ws)

                    async for message in ws:
                        data = json.loads(message)
                        await self.handle_tick(data)

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(5)

    async def handle_tick(self, data: dict):
        """
        Normalize & push tick to context bus
        """
        if "symbol" not in data:
            return

        tick = {
            "symbol": data["symbol"],
            "bid": data.get("bid"),
            "ask": data.get("ask"),
            "timestamp": data.get("timestamp"),
            "source": "twelvedata_ws",
        }

        self.context_bus.update_tick(tick)
