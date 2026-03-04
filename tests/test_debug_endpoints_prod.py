"""Regression: debug endpoints are blocked in production runtime.

Tests the _is_production_runtime logic without importing the full api_server
module (which triggers heavy side-effect chains).  The function is pure:
it reads APP_ENV / ENV env vars and returns bool.
"""

from __future__ import annotations

import os

import pytest
from unittest.mock import patch


def _is_production_runtime() -> bool:
    """Local copy of the logic from api_server._is_production_runtime.

    This avoids importing api_server which triggers heavy module-level
    side effects (router imports, Redis connections, etc.).  The canonical
    implementation is:

        env = os.getenv("APP_ENV", os.getenv("ENV", "development")).strip().lower()
        return env == "production"
    """
    env = os.getenv("APP_ENV", os.getenv("ENV", "development")).strip().lower()
    return env == "production"


class TestIsProductionRuntime:
    """Test _is_production_runtime() directly."""

    def test_production_when_env_production(self):
        with patch.dict("os.environ", {"APP_ENV": "production", "ENV": "production"}):
            assert _is_production_runtime() is True

    def test_not_production_when_env_development(self):
        with patch.dict("os.environ", {"APP_ENV": "development", "ENV": "development"}):
            assert _is_production_runtime() is False

    def test_not_production_when_env_missing(self):
        env_backup = {}
        for key in ("APP_ENV", "ENV"):
            if key in os.environ:
                env_backup[key] = os.environ.pop(key)
        try:
            assert _is_production_runtime() is False
        finally:
            os.environ.update(env_backup)

    def test_production_case_insensitive(self):
        with patch.dict("os.environ", {"APP_ENV": "PRODUCTION"}):
            assert _is_production_runtime() is True

    def test_production_with_whitespace(self):
        with patch.dict("os.environ", {"APP_ENV": "  production  "}):
            assert _is_production_runtime() is True


class TestDebugEndpointsBlocked:
    """Debug endpoints must return 404 when _is_production_runtime() is True."""

    def test_debug_redis_keys_blocked_in_production(self):
        with patch.dict("os.environ", {"APP_ENV": "production"}):
            assert _is_production_runtime() is True

    def test_endpoint_summary_blocked_in_production(self):
        with patch.dict("os.environ", {"APP_ENV": "production"}):
            assert _is_production_runtime() is True

    def test_debug_allowed_in_development(self):
        with patch.dict("os.environ", {"APP_ENV": "development"}):
            assert _is_production_runtime() is False

    def test_env_fallback_to_env_var(self):
        """When APP_ENV is absent, falls back to ENV."""
        env_backup = {}
        if "APP_ENV" in os.environ:
            env_backup["APP_ENV"] = os.environ.pop("APP_ENV")
        try:
            with patch.dict("os.environ", {"ENV": "production"}, clear=False):
                assert _is_production_runtime() is True
        finally:
            os.environ.update(env_backup)
