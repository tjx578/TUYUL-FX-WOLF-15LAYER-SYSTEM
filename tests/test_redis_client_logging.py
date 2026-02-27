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
