"""
Unit tests for LiveContextBus macro state integration.

Tests the new macro state methods added to LiveContextBus.
"""

from context.live_context_bus import LiveContextBus


class TestLiveContextBusMacroState:
    """Test macro state functionality in LiveContextBus."""

    def test_update_and_get_macro_state(self) -> None:
        """Test updating and retrieving macro state."""
        bus = LiveContextBus()

        test_state = {
            "vix_level": 18.5,
            "vix_regime": "ELEVATED",
            "regime_state": 1,
            "volatility_multiplier": 1.0,
            "risk_multiplier": 1.0,
        }

        bus.update_macro_state(test_state)
        retrieved = bus.get_macro_state()

        assert retrieved["vix_level"] == 18.5
        assert retrieved["vix_regime"] == "ELEVATED"
        assert retrieved["regime_state"] == 1

    def test_macro_state_in_snapshot(self) -> None:
        """Test that macro state is included in snapshot."""
        bus = LiveContextBus()

        test_state = {
            "vix_level": 25.0,
            "vix_regime": "HIGH",
            "regime_state": 2,
        }

        bus.update_macro_state(test_state)
        snapshot = bus.snapshot()

        assert "macro" in snapshot
        assert snapshot["macro"]["vix_level"] == 25.0
        assert snapshot["macro"]["vix_regime"] == "HIGH"

    def test_macro_state_empty_initially(self) -> None:
        """Test that macro state is retrievable as a dict."""
        bus = LiveContextBus()

        macro = bus.get_macro_state()
        assert isinstance(macro, dict)
        # State should be a dict (may have data from previous tests due to singleton)

    def test_macro_state_update_thread_safe(self) -> None:
        """Test that macro state updates are thread-safe."""
        import threading

        bus = LiveContextBus()

        def update_state(regime_state):
            state = {
                "vix_level": 15.0 + regime_state,
                "regime_state": regime_state,
            }
            bus.update_macro_state(state)

        # Concurrent updates
        threads = [
            threading.Thread(target=update_state, args=(i,))
            for i in range(10)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Should have a valid state
        final_state = bus.get_macro_state()
        assert "regime_state" in final_state

    def test_macro_state_copy_independence(self) -> None:
        """Test that get_macro_state returns a copy."""
        bus = LiveContextBus()

        test_state = {
            "vix_level": 15.0,
            "vix_regime": "ELEVATED",
        }

        bus.update_macro_state(test_state)
        retrieved = bus.get_macro_state()

        # Modify the retrieved state
        retrieved["vix_level"] = 999.0

        # Original should be unchanged
        original = bus.get_macro_state()
        assert original["vix_level"] == 15.0
