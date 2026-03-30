"""TUYUL Trading Swarm — Main entrypoint.

Run modes:
  all      — API server (default)
  api-only — API server only
"""
from __future__ import annotations

import asyncio
import os
import sys

import uvicorn
from loguru import logger

RUN_MODE = os.getenv("RUN_MODE", "all").lower()
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").lower()


def main() -> None:
    logger.info(f"Starting TUYUL Trading Swarm — mode: {RUN_MODE}")

    config = uvicorn.Config(
        "api_server:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL,
        workers=1,
        reload=os.getenv("APP_ENV", "prod") == "dev",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
