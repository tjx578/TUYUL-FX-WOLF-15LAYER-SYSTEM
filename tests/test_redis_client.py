"""Tests for infrastructure/redis_client.py — native async, no run_in_executor."""

from __future__ import annotations

import os
from unittest.mock import patch

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

    def test_from_env_individual_vars_override_url(self) -> None:
        """Individual REDIS_HOST/PORT/etc take priority over REDIS_URL components."""
        with patch.dict(os.environ, {
            "REDIS_URL": "redis://url-host:6000/0",
            "REDIS_HOST": "override-host",
            "REDIS_PORT": "6001",
        }):
            cfg = RedisConfig.from_env()
            assert cfg.host == "override-host"
            assert cfg.port == 6001

    def test_empty_password_becomes_none(self) -> None:
        with patch.dict(os.environ, {"REDIS_PASSWORD": ""}):
            cfg = RedisConfig.from_env()
            assert cfg.password is None

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
