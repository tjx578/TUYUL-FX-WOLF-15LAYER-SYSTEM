"""Dedicated engine process entrypoint (no public HTTP)."""

import asyncio
import os

from loguru import logger
from config.logging_bootstrap import configure_loguru_logging

from main import main as run_main


configure_loguru_logging()


def run() -> None:
    os.environ["RUN_MODE"] = "engine-only"
    logger.info("Starting wolf15-engine service (HTTP disabled)")
    asyncio.run(run_main())


if __name__ == "__main__":
    run()
