"""
TUYUL FX — WOLF 15-LAYER SYSTEM
ENTRY POINT (DO NOT PUT LOGIC HERE)
"""

import asyncio
from loguru import logger

from ingest.twelve_data_ws import TwelveDataWebSocket
from ingest.twelve_data_news import TwelveDataNews
from ingest.candle_builder import CandleBuilder


async def main():
    logger.info("🐺 TUYUL FX WOLF 15-LAYER SYSTEM STARTING...")

    # --- INGEST SERVICES ---
    ws_feed = TwelveDataWebSocket()
    news_feed = TwelveDataNews()
    candle_builder = CandleBuilder()

    await asyncio.gather(
        ws_feed.run(),
        news_feed.run(),
        candle_builder.run(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("SYSTEM SHUTDOWN BY USER")
# Placeholder
