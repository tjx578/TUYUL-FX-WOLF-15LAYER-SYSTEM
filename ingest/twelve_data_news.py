import os
import asyncio
import requests
from loguru import logger

from config_loader import load_twelve_data
from context.live_context_bus import LiveContextBus


class TwelveDataNews:
    """
    Economic calendar & news ingestion
    NO TRADING DECISION
    """

    def __init__(self):
        self.config = load_twelve_data()
        self.api_key = os.getenv("TWELVE_DATA_API_KEY")
        self.rest_url = os.getenv("TWELVE_DATA_REST_URL")
        self.context_bus = LiveContextBus()

    async def fetch_news(self):
        url = f"{self.rest_url}/economic_calendar"
        params = {
            "apikey": self.api_key,
        }

        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    async def run(self):
        if not self.config["news"]["enabled"]:
            logger.warning("News ingestion disabled.")
            return

        while True:
            try:
                data = await self.fetch_news()
                self.context_bus.update_news(data)
                logger.info("Economic calendar updated")

            except Exception as e:
                logger.error(f"News fetch error: {e}")

            await asyncio.sleep(300)  # every 5 minutes
# Placeholder
