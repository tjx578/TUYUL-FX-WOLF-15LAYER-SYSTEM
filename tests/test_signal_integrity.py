"""
Tests for signal integrity -- expiry, dedup, validation.
"""

import time

import pytest  # pyright: ignore[reportMissingImports]

from constitution.signal_integrity import SignalIntegrityGuard, SignalMetadata


@pytest.fixture
def guard():
    return SignalIntegrityGuard(expiry_seconds=60)


class TestSignalGeneration:
    def test_generates_unique_ids(self, guard):
        m1, new1 = guard.create_metadata("EURUSD", "BUY", 1.10000, 1.09500, "H1")
        # Slightly different entry to avoid dedup
        m2, new2 = guard.create_metadata("EURUSD", "BUY", 1.10010, 1.09500, "H1")
        assert new1 is True
        assert new2 is True
        assert m1.signal_id != m2.signal_id

    def test_detects_duplicates(self, guard):
        _m1, new1 = guard.create_metadata("EURUSD", "BUY", 1.10000, 1.09500, "H1")
        m2, new2 = guard.create_metadata("EURUSD", "BUY", 1.10000, 1.09500, "H1")
        assert new1 is True
        assert new2 is False
        assert m2.signal_id == "DUPLICATE"


class TestSignalExpiry:
    def test_fresh_signal_is_valid(self, guard):
        meta, _ = guard.create_metadata("GBPUSD", "SELL", 1.30000, 1.30500, "M15")
        valid, _reason = guard.validate_for_execution(meta)
        assert valid is True

    def test_expired_signal_is_rejected(self, guard):
        meta = SignalMetadata(
            signal_id="SIG-TEST",
            created_at=time.time() - 120,
            expires_at=time.time() - 60,
            analysis_hash="abc123",
        )
        valid, reason = guard.validate_for_execution(meta)
        assert valid is False
        assert "EXPIRED" in reason

    def test_duplicate_signal_is_rejected(self, guard):
        meta = SignalMetadata(
            signal_id="DUPLICATE",
            created_at=time.time(),
            expires_at=0,
            analysis_hash="abc",
        )
        valid, reason = guard.validate_for_execution(meta)
        assert valid is False
        assert "DUPLICATE" in reason
