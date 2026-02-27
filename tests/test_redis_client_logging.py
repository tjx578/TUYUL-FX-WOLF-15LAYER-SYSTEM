"""Tests for Redis logging safety helpers."""

import os
from unittest.mock import patch

from infrastructure.redis_url import get_safe_redis_url
from storage.redis_client import _sanitize_redis_url


def test_sanitize_redis_url_masks_password() -> None:
    url = "redis://default:supersecret@redis.railway.internal:6379"
    safe = _sanitize_redis_url(url)

    assert "supersecret" not in safe
    assert safe == "redis://default:***@redis.railway.internal:6379"


def test_sanitize_redis_url_without_credentials_is_unchanged() -> None:
    url = "redis://localhost:6379/0"
    assert _sanitize_redis_url(url) == url


def test_sanitize_redis_url_with_username_only_is_unchanged() -> None:
    url = "redis://default@localhost:6379/0"
    assert _sanitize_redis_url(url) == url


def test_get_safe_redis_url_masks_password_from_env() -> None:
    with patch.dict(os.environ, {"REDIS_URL": "redis://default:supersecret@redis.railway.internal:6379"}, clear=True):
        safe = get_safe_redis_url()

    assert "supersecret" not in safe
    assert safe == "redis://default:***@redis.railway.internal:6379"


def test_get_safe_redis_url_uses_default_without_credentials() -> None:
    with patch.dict(os.environ, {}, clear=True):
        safe = get_safe_redis_url()

    assert safe == "redis://localhost:6379/0"


def test_get_redis_url_falls_back_to_railway_vars() -> None:
    """When REDIS_URL is absent, build URL from REDISHOST/PORT/etc."""
    from infrastructure.redis_url import get_redis_url

    env = {
        "REDISHOST": "railway-host.internal",
        "REDISPORT": "6380",
        "REDISUSER": "default",
        "REDISPASSWORD": "railwaypass",
    }
    with patch.dict(os.environ, env, clear=True):
        url = get_redis_url()

    assert "railway-host.internal" in url
    assert ":6380" in url
    assert "railwaypass" in url


def test_redis_url_takes_priority_over_railway_vars() -> None:
    """REDIS_URL always wins when both are set."""
    from infrastructure.redis_url import get_redis_url

    env = {
        "REDIS_URL": "redis://explicit-host:6379/0",
        "REDISHOST": "railway-host.internal",
    }
    with patch.dict(os.environ, env, clear=True):
        url = get_redis_url()

    assert url == "redis://explicit-host:6379/0"
