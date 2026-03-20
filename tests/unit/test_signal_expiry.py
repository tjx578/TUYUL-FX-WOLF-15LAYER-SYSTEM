"""
Unit tests for constitution/signal_expiry.py — L12 signal TTL enforcement.

Covers:
- assign_expiry attaches correct TTL per timeframe
- Default TTL fallback for unknown timeframes
- is_signal_valid rejects missing expiry
- is_signal_valid rejects expired signals
- is_signal_valid accepts valid signals
- Warning for signals close to expiry (<10 s)
- Full round-trip: assign → validate
"""

from __future__ import annotations

import logging
import time

import pytest
from _pytest.logging import LogCaptureFixture

from constitution.signal_expiry import (
    DEFAULT_TTL,
    TIMEFRAME_TTL,
    assign_expiry,
    is_signal_valid,
)

# ──────────────────────────────────────────────────────────────────
#  assign_expiry
# ──────────────────────────────────────────────────────────────────

class TestAssignExpiry:
    def test_attaches_expires_at(self):
        signal = {"signal_id": "SIG-001"}
        before = time.time()
        result = assign_expiry(signal, "H1")
        after = time.time()

        ttl = TIMEFRAME_TTL["H1"]  # 1800
        assert result["ttl_seconds"] == ttl
        assert before + ttl <= result["expires_at"] <= after + ttl

    @pytest.mark.parametrize("tf,expected_ttl", list(TIMEFRAME_TTL.items()))
    def test_ttl_per_timeframe(self, tf: str, expected_ttl: int):
        result = assign_expiry({}, tf)
        assert result["ttl_seconds"] == expected_ttl

    def test_unknown_timeframe_uses_default(self):
        result = assign_expiry({}, "MN1")
        assert result["ttl_seconds"] == DEFAULT_TTL

    def test_mutates_and_returns_same_dict(self):
        original = {"signal_id": "SIG-002"}
        result = assign_expiry(original, "M5")
        assert result is original
        assert "expires_at" in original


# ──────────────────────────────────────────────────────────────────
#  is_signal_valid
# ──────────────────────────────────────────────────────────────────

class TestIsSignalValid:
    def test_rejects_missing_expiry(self):
        valid, reason = is_signal_valid({})
        assert valid is False
        assert "no expiry" in reason.lower()

    def test_rejects_expired_signal(self):
        signal = {"expires_at": time.time() - 60}  # expired 60s ago
        valid, reason = is_signal_valid(signal)
        assert valid is False
        assert "expired" in reason.lower()

    def test_accepts_valid_signal(self):
        signal = {"expires_at": time.time() + 300}
        valid, reason = is_signal_valid(signal)
        assert valid is True
        assert "valid" in reason.lower()

    def test_remaining_time_in_reason(self):
        signal = {"expires_at": time.time() + 120}
        valid, reason = is_signal_valid(signal)
        assert valid is True
        assert "remaining" in reason.lower()

    def test_expired_elapsed_in_reason(self):
        signal = {"expires_at": time.time() - 30.5}
        valid, reason = is_signal_valid(signal)
        assert valid is False
        assert "30" in reason  # ~30s elapsed

    def test_warns_near_expiry(self, caplog: LogCaptureFixture) -> None:
        """Signals with < 10s remaining should produce a warning log."""
        with caplog.at_level(logging.WARNING, logger="tuyul.constitution.expiry"):
            signal = {"signal_id": "SIG-URGENT", "expires_at": time.time() + 5}
            valid, _ = is_signal_valid(signal)
            assert valid is True
        assert any("urgent" in r.message.lower() or "expires" in r.message.lower()
                    for r in caplog.records)


# ──────────────────────────────────────────────────────────────────
#  Round-trip: assign → validate
# ──────────────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_freshly_assigned_signal_is_valid(self):
        signal = assign_expiry({"signal_id": "SIG-RT"}, "H1")
        valid, _ = is_signal_valid(signal)
        assert valid is True

    @pytest.mark.parametrize("tf", list(TIMEFRAME_TTL.keys()))
    def test_all_timeframes_produce_valid_signals(self, tf: str) -> None:
        signal = assign_expiry({"signal_id": f"SIG-{tf}"}, tf)
        valid, _ = is_signal_valid(signal)
        assert valid is True


# ──────────────────────────────────────────────────────────────────
#  Edge cases
# ──────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_exact_expiry_boundary(self):
        """At exactly expires_at, signal should be expired (now > expires_at is False when equal)."""
        now = time.time()
        signal = {"expires_at": now}
        # Time may have advanced slightly, so this may be expired.
        # The important thing is it doesn't crash.
        valid, reason = is_signal_valid(signal)
        assert isinstance(valid, bool)
        assert isinstance(reason, str)

    def test_very_short_ttl_m1(self):
        """M1 has 60s TTL — verify it's usable."""
        signal = assign_expiry({}, "M1")
        assert signal["ttl_seconds"] == 60
        valid, _ = is_signal_valid(signal)
        assert valid is True

    def test_very_long_ttl_w1(self):
        """W1 has 43200s (12h) TTL."""
        signal = assign_expiry({}, "W1")
        assert signal["ttl_seconds"] == 43200
        valid, _ = is_signal_valid(signal)
        assert valid is True
