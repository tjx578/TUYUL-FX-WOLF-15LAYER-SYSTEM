"""Tests for ingest_service module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_ingest_services_closes_redis_when_ping_fails():
    """Redis.aclose() must be awaited when ping raises an exception."""
    from ingest_service import run_ingest_services

    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    mock_redis.aclose = AsyncMock()

    with patch("ingest_service._build_redis_client", return_value=mock_redis):
        with pytest.raises(ConnectionError, match="Redis unavailable"):
            await run_ingest_services(has_api_key=True)

    mock_redis.aclose.assert_awaited_once()
