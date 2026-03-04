"""Tests for ingest.finnhub_key_manager and rate_limit path bucket fixes."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest


# =========================================================================
# FinnhubKeyManager
# =========================================================================


class TestFinnhubKeyManager:
    """Unit tests for key loading, rotation, and failure tracking."""

    def _make_manager(self, env: dict[str, str]) -> "FinnhubKeyManager":
        """Create a fresh manager with custom env vars."""
        with patch.dict(os.environ, env, clear=False):
            # Force fresh import to re-read env
            from ingest.finnhub_key_manager import FinnhubKeyManager
            return FinnhubKeyManager()

    # ── Loading ────────────────────────────────────────────────────

    def test_no_keys(self):
        mgr = self._make_manager({"FINNHUB_API_KEY": "", "FINNHUB_API_KEY_SECONDARY": "", "FINNHUB_API_KEYS": ""})
        assert not mgr.available
        assert mgr.current_key() == ""
        assert mgr.key_count == 0

    def test_single_key(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEY": "pk_abc",
            "FINNHUB_API_KEY_SECONDARY": "",
            "FINNHUB_API_KEYS": "",
        })
        assert mgr.available
        assert mgr.current_key() == "pk_abc"
        assert mgr.key_count == 1

    def test_primary_plus_secondary(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEY": "pk_a",
            "FINNHUB_API_KEY_SECONDARY": "pk_b",
            "FINNHUB_API_KEYS": "",
        })
        assert mgr.key_count == 2
        assert mgr.current_key() == "pk_a"

    def test_comma_separated_keys(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEYS": "k1, k2, k3",
            "FINNHUB_API_KEY": "ignored",
            "FINNHUB_API_KEY_SECONDARY": "ignored",
        })
        assert mgr.key_count == 3
        assert mgr.current_key() == "k1"

    def test_dedup_comma_keys(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEYS": "k1,k1,k2",
            "FINNHUB_API_KEY": "",
            "FINNHUB_API_KEY_SECONDARY": "",
        })
        assert mgr.key_count == 2

    def test_placeholder_key_ignored(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEY": "YOUR_FINNHUB_API_KEY",
            "FINNHUB_API_KEY_SECONDARY": "",
            "FINNHUB_API_KEYS": "",
        })
        assert not mgr.available

    # ── Rotation on failure ────────────────────────────────────────

    def test_rotation_on_429(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEYS": "k1,k2",
            "FINNHUB_API_KEY": "",
            "FINNHUB_API_KEY_SECONDARY": "",
        })
        assert mgr.current_key() == "k1"
        mgr.report_failure("k1", 429)
        assert mgr.current_key() == "k2"

    def test_rotation_on_401(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEYS": "k1,k2",
            "FINNHUB_API_KEY": "",
            "FINNHUB_API_KEY_SECONDARY": "",
        })
        mgr.report_failure("k1", 401)
        assert mgr.current_key() == "k2"

    def test_no_rotation_on_single_key(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEY": "solo",
            "FINNHUB_API_KEY_SECONDARY": "",
            "FINNHUB_API_KEYS": "",
        })
        mgr.report_failure("solo", 429)
        # Still returns the only key — no better option.
        assert mgr.current_key() == "solo"

    def test_all_keys_suspended(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEYS": "k1,k2",
            "FINNHUB_API_KEY": "",
            "FINNHUB_API_KEY_SECONDARY": "",
        })
        mgr.report_failure("k1", 429)
        mgr.report_failure("k2", 429)
        # Both suspended — returns whatever is active (still functional, just degraded)
        key = mgr.current_key()
        assert key in {"k1", "k2"}

    def test_success_resets_failures(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEYS": "k1,k2",
            "FINNHUB_API_KEY": "",
            "FINNHUB_API_KEY_SECONDARY": "",
        })
        mgr.report_failure("k1", 429)
        mgr.report_success("k1")
        # After success, k1 should be usable again
        status = mgr.status()
        k1_status = [s for s in status if s["index"] == 0][0]
        assert k1_status["failures"] == 0
        assert not k1_status["suspended"]

    def test_non_rotatable_status_codes_ignored(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEYS": "k1,k2",
            "FINNHUB_API_KEY": "",
            "FINNHUB_API_KEY_SECONDARY": "",
        })
        mgr.report_failure("k1", 500)  # Should NOT trigger suspension
        assert mgr.current_key() == "k1"  # Still on k1

    # ── Diagnostics ────────────────────────────────────────────────

    def test_status_masks_keys(self):
        mgr = self._make_manager({
            "FINNHUB_API_KEY": "pk_abcdefgh1234",
            "FINNHUB_API_KEY_SECONDARY": "",
            "FINNHUB_API_KEYS": "",
        })
        status = mgr.status()
        assert len(status) == 1
        assert "****" in status[0]["masked_key"]
        assert "pk_abcdefgh1234" not in status[0]["masked_key"]


# =========================================================================
# Rate limit _path_bucket fixes
# =========================================================================


class TestPathBucketMatching:
    """Verify rate limit buckets match actual API paths (e.g. /api/v1/...)."""

    def test_ea_restart_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/ea/restart", "POST", False)
        assert result is not None
        assert result[0] == "ea_control"

    def test_ea_safe_mode_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/ea/safe-mode", "POST", False)
        assert result is not None
        assert result[0] == "ea_control"

    def test_account_write_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/accounts/acc-123", "PUT", False)
        assert result is not None
        assert result[0] == "account_write"

    def test_account_create_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/accounts", "POST", False)
        assert result is not None
        assert result[0] == "account_write"

    def test_trade_take_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/trades/take", "POST", False)
        assert result is not None
        assert result[0] == "take"

    def test_trade_confirm_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/trades/confirm", "POST", False)
        assert result is not None
        assert result[0] == "trade_write"

    def test_risk_calculate_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/risk/calculate", "POST", False)
        assert result is not None
        assert result[0] == "risk_calc"

    def test_config_profiles_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/config/profiles", "POST", False)
        assert result is not None
        assert result[0] == "config_write"

    def test_ws_connect_matches(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/ws/prices", "GET", True)
        assert result is not None
        assert result[0] == "ws_connect"

    def test_get_request_returns_none(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/accounts", "GET", False)
        assert result is None

    def test_admin_redis_candle_delete(self):
        from api.middleware.rate_limit import _path_bucket
        result = _path_bucket("/api/v1/redis/candles/EURUSD", "DELETE", False)
        assert result is not None
        assert result[0] == "admin"
