"""Dedicated ingest process entrypoint."""

import asyncio

from loguru import logger
from config.logging_bootstrap import configure_loguru_logging

from ingest_service import main as run_main


configure_loguru_logging()


def run() -> None:
    logger.info("Starting wolf15-ingest service")
    asyncio.run(run_main())


if __name__ == "__main__":
    run()
