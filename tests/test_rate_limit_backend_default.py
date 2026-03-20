"""Tests for rate-limit backend default selection."""

from __future__ import annotations

import importlib
import sys

import pytest


def _reload_rate_limit_module():
    module_name = "api.middleware.rate_limit"
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


class TestRateLimitBackendDefault:
    def test_defaults_to_redis_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RATE_LIMIT_BACKEND", raising=False)
        monkeypatch.setenv("ENV", "production")

        mod = _reload_rate_limit_module()
        assert mod.RATE_LIMIT_BACKEND == "redis"

    def test_defaults_to_memory_in_non_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RATE_LIMIT_BACKEND", raising=False)
        monkeypatch.setenv("ENV", "development")

        mod = _reload_rate_limit_module()
        assert mod.RATE_LIMIT_BACKEND == "memory"
