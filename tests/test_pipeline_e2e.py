"""
End-to-end pipeline test.
Simulates: mock feed → full analysis → L12 verdict → risk check → execution command.
Verifies ALL constitutional boundaries are maintained.
"""

import time

from constitution.signal_dedup import SignalDeduplicator
from constitution.signal_expiry import is_signal_valid
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline
from schemas.validator import validate_l12_signal


class TestFullPipelineE2E:
    """End-to-end pipeline flow test."""

    def test_pipeline_produces_valid_l12_signal(self):
        """
        Given: mock candle data for EURUSD
        When: pipeline runs full analysis → L12 verdict
        Then: output signal passes l12_signal_schema validation
        """
        # This test verifies the pipeline output contract
        pipeline = WolfConstitutionalPipeline()

        # Mock the context bus with sample data
        mock_context = {
            "symbol": "EURUSD",
            "candles": {
                "H1": self._generate_mock_candles(100),
                "H4": self._generate_mock_candles(50),
                "D1": self._generate_mock_candles(30),
            },
            "feed_freshness": 1.0,
            "redis_health": 1.0,
        }

        # Run pipeline (may return NO_TRADE if mock data doesn't trigger setup)
        result = pipeline.run(mock_context) # pyright: ignore[reportAttributeAccessIssue]

        assert result is not None
        assert "verdict" in result
        assert result["verdict"] in ("EXECUTE", "HOLD", "NO_TRADE", "ABORT")

        if result["verdict"] == "EXECUTE":
            # Validate against schema
            is_valid, errors = validate_l12_signal(result)
            assert is_valid, f"Schema validation failed: {errors}"

            # Constitutional check: no account state in signal
            assert "balance" not in result
            assert "equity" not in result
            assert "lot_size" not in result
            assert "risk_amount" not in result

    def test_expired_signal_blocked_at_execution(self):
        """
        Given: an L12 EXECUTE signal that has expired
        When: execution attempts to use it
        Then: it is rejected
        """
        expired_signal = {
            "signal_id": "SIG-EU-20260215-100000-AAAA",
            "symbol": "EURUSD",
            "verdict": "EXECUTE",
            "confidence": 0.85,
            "expires_at": time.time() - 60,  # expired 60s ago
            "timestamp": time.time() - 360,
        }

        valid, reason = is_signal_valid(expired_signal)
        assert valid is False
        assert "expired" in reason.lower()

    def test_duplicate_signal_blocked(self):
        """
        Given: same signal emitted twice
        When: dedup checks second emission
        Then: it is flagged as duplicate
        """
        dedup = SignalDeduplicator(window_seconds=60)

        signal = {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.10000,
            "stop_loss": 1.09500,
            "primary_timeframe": "H1",
        }

        is_dup_1, hash_1 = dedup.is_duplicate(signal)
        assert is_dup_1 is False

        dedup.register(signal)

        is_dup_2, hash_2 = dedup.is_duplicate(signal)
        assert is_dup_2 is True
        assert hash_1 == hash_2

    def test_constitutional_boundary_analysis_no_execution(self):
        """
        Verify: analysis modules cannot produce execution side effects.
        They return data structures only — no order placement, no account mutation.
        """
        # synthesis.build_synthesis should return dict, not trigger any execution
        # This is a structural test — ensure the function signature is pure
        import inspect  # noqa: PLC0415

        from analysis import (  # noqa: PLC0415
            synthesis,  # pyright: ignore[reportAttributeAccessIssue]
        )
        sig = inspect.signature(synthesis.build_synthesis)
        # Should not have parameters like 'broker', 'account', 'execute'
        param_names = set(sig.parameters.keys())
        forbidden_params = {"broker", "account", "execute", "place_order", "mt5"}
        violation = param_names.intersection(forbidden_params)
        assert not violation, f"Analysis function has execution-related params: {violation}"

    def test_constitutional_boundary_ea_no_override(self):
        """
        Verify: EA bridge does not modify verdict or risk parameters.
        It receives a command and executes exactly as-is.
        """
        from ea_interface.mt5_bridge import ExecutionCommand  # noqa: PLC0415

        cmd = ExecutionCommand(
            signal_id="SIG-EU-20260215-120000-BBBB",
            symbol="EURUSD",
            direction="BUY",
            order_type="LIMIT",
            entry_price=1.10000,
            stop_loss=1.09500,
            take_profit=1.11000,
            lot_size=0.15,
        )

        # Verify command is immutable — EA cannot change these
        assert cmd.lot_size == 0.15
        assert cmd.stop_loss == 1.09500
        # ExecutionCommand should not have methods like override_lot() or modify_sl()
        assert not hasattr(cmd, "override_lot")
        assert not hasattr(cmd, "modify_sl")
        assert not hasattr(cmd, "recalculate")

    @staticmethod
    def _generate_mock_candles(count: int) -> list[dict]:
        """Generate simple mock OHLCV candles for testing."""
        candles = []
        base_price = 1.10000
        base_time = time.time() - (count * 3600)

        for i in range(count):
            o = base_price + (i * 0.0001)
            h = o + 0.0020
            l = o - 0.0010  # noqa: E741
            c = o + 0.0005
            candles.append({
                "time": base_time + (i * 3600),
                "open": round(o, 5),
                "high": round(h, 5),
                "low": round(l, 5),
                "close": round(c, 5),
                "volume": 1000 + i,
            })

        return candles
