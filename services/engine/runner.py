"""Dedicated engine process entrypoint (no public HTTP)."""

from __future__ import annotations

import asyncio
import os

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from config.logging_bootstrap import configure_loguru_logging
from main import main as run_main
from services.shared.db_revision_guard import DatabaseSchemaError, assert_required_tables


configure_loguru_logging()

REQUIRED_TABLES: tuple[str, ...] = ("trade_outbox",)


def _build_engine_from_env() -> AsyncEngine:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return create_async_engine(database_url, pool_pre_ping=True, future=True)


async def _preflight_checks() -> None:
    engine = _build_engine_from_env()
    try:
        await assert_required_tables(engine, REQUIRED_TABLES)
        logger.info("DB schema preflight passed", required_tables=REQUIRED_TABLES)
    finally:
        await engine.dispose()


def run() -> None:
    os.environ["RUN_MODE"] = "engine-only"
    logger.info("Starting wolf15-engine service (HTTP disabled)")

    try:
        asyncio.run(_preflight_checks())
    except DatabaseSchemaError:
        logger.exception("Engine startup blocked: database schema is not ready")
        raise

    asyncio.run(run_main())


if __name__ == "__main__":
    run()
