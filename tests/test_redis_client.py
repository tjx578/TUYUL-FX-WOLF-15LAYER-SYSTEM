"""Tests for infrastructure/redis_client.py — native async, no run_in_executor."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from infrastructure.redis_client import RedisClientManager, RedisConfig


class TestRedisConfig:
    def test_defaults(self) -> None:
        cfg = RedisConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 6379
        assert cfg.password is None
        assert cfg.decode_responses is True

    def test_from_env(self) -> None:
        env = {
            "REDIS_HOST": "redis.prod.internal",
            "REDIS_PORT": "6380",
            "REDIS_PASSWORD": "s3cret",
            "REDIS_DB": "2",
        }
        with patch.dict(os.environ, env):
            cfg = RedisConfig.from_env()
            assert cfg.host == "redis.prod.internal"
            assert cfg.port == 6380
            assert cfg.password == "s3cret"
            assert cfg.db == 2

    def test_from_env_defaults(self) -> None:
        # When all env vars are cleared, get_redis_url() returns the hardcoded
        # default "redis://localhost:6379/0", so host resolves to "localhost".
        with patch.dict(os.environ, {}, clear=True):
            cfg = RedisConfig.from_env()
            assert cfg.host == "localhost"
            assert cfg.port == 6379
            assert cfg.password is None

    def test_from_env_redis_url(self) -> None:
        """REDIS_URL is the primary config source (Railway / Docker)."""
        with patch.dict(os.environ, {"REDIS_URL": "redis://:s3cret@redis.railway.internal:6380/3"}, clear=True):
            cfg = RedisConfig.from_env()
            assert cfg.host == "redis.railway.internal"
            assert cfg.port == 6380
            assert cfg.password == "s3cret"
            assert cfg.db == 3

    def test_from_env_redis_private_url(self) -> None:
        """REDIS_PRIVATE_URL is used when REDIS_URL is absent (Railway private network)."""
        with patch.dict(os.environ, {"REDIS_PRIVATE_URL": "redis://:pass@redis.railway.internal:6379/0"}, clear=True):
            cfg = RedisConfig.from_env()
            assert cfg.host == "redis.railway.internal"
            assert cfg.port == 6379
            assert cfg.password == "pass"

    def test_redis_url_takes_priority_over_private_url(self) -> None:
        """REDIS_URL takes priority over REDIS_PRIVATE_URL."""
        with patch.dict(
            os.environ,
            {
                "REDIS_URL": "redis://url-host:6001/0",
                "REDIS_PRIVATE_URL": "redis://private-host:6002/0",
            },
            clear=True,
        ):
            cfg = RedisConfig.from_env()
            assert cfg.host == "url-host"
            assert cfg.port == 6001

    def test_from_env_individual_vars_override_url(self) -> None:
        """Individual REDIS_HOST/PORT/etc take priority over REDIS_URL components."""
        with patch.dict(
            os.environ,
            {
                "REDIS_URL": "redis://url-host:6000/0",
                "REDIS_HOST": "override-host",
                "REDIS_PORT": "6001",
            },
        ):
            cfg = RedisConfig.from_env()
            assert cfg.host == "override-host"
            assert cfg.port == 6001

    def test_empty_password_becomes_none(self) -> None:
        with patch.dict(os.environ, {"REDIS_PASSWORD": ""}):
            cfg = RedisConfig.from_env()
            assert cfg.password is None

    def test_railway_style_vars_fallback(self) -> None:
        """Railway-style vars (REDISHOST etc.) used when standard vars absent."""
        env = {
            "REDISHOST": "railway-host.internal",
            "REDISPORT": "6380",
            "REDISPASSWORD": "railwaypass",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = RedisConfig.from_env()
            assert cfg.host == "railway-host.internal"
            assert cfg.port == 6380
            assert cfg.password == "railwaypass"

    def test_standard_vars_override_railway_vars(self) -> None:
        """REDIS_HOST takes priority over REDISHOST."""
        env = {
            "REDIS_HOST": "standard-host",
            "REDISHOST": "railway-host",
            "REDIS_PORT": "6381",
            "REDISPORT": "6380",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = RedisConfig.from_env()
            assert cfg.host == "standard-host"
            assert cfg.port == 6381

    def test_frozen(self) -> None:
        cfg = RedisConfig()
        with pytest.raises(AttributeError):
            cfg.host = "changed"  # type: ignore[misc]


class TestRedisClientManager:
    @pytest.mark.asyncio
    async def test_close_without_pool(self) -> None:
        """Close on uninitialized manager should not raise."""
        mgr = RedisClientManager()
        await mgr.close()  # No error

    @pytest.mark.asyncio
    async def test_pool_has_retry_config(self) -> None:
        """Pool must be created with a Retry object and retry_on_error list."""
        from redis.retry import Retry

        mgr = RedisClientManager()
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}, clear=True):
            pool = await mgr.get_pool()
            # ConnectionPool.from_url passes retry/retry_on_error to
            # connection_kwargs; verify they propagate.
            ckw: dict[str, object] = dict(pool.connection_kwargs)  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            assert "retry" in ckw, "Retry object must be set on pool"
            assert isinstance(ckw["retry"], Retry)
            assert ckw.get("retry_on_error") is not None
            await mgr.close()

    @pytest.mark.asyncio
    async def test_reset_pool_clears_and_recreates(self) -> None:
        """reset_pool should close the old pool and pre-warm a new one."""
        mgr = RedisClientManager()
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}, clear=True):
            pool1 = await mgr.get_pool()
            # Mock aclose so it doesn't actually talk to Redis
            pool1.aclose = AsyncMock()
            await mgr.reset_pool()
            pool1.aclose.assert_awaited_once()
            # A new pool should have been created (pre-warm)
            pool2 = await mgr.get_pool()
            assert pool2 is not pool1
            await mgr.close()
