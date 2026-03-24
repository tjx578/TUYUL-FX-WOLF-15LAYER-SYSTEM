"""
Unit tests for SystemStateManager.

Tests state transitions, validation, and per-symbol status tracking.
"""
from __future__ import annotations

import pytest

from context.system_state import (
    SymbolStatus,
    SystemState,
    SystemStateManager,
    WarmupStatus,
)


class TestStateTransitions:
    """Test valid and invalid state transitions."""

    def test_initializing_to_warming_up(self) -> None:
        """Test INITIALIZING -> WARMING_UP transition."""
        manager = SystemStateManager()
        # Force reset to INITIALIZING
        with manager._rw_lock:
            manager._state = SystemState.INITIALIZING

        manager.set_state(SystemState.WARMING_UP)
        assert manager.get_state() == SystemState.WARMING_UP

    def test_warming_up_to_ready(self) -> None:
        """Test WARMING_UP -> READY transition."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.WARMING_UP

        manager.set_state(SystemState.READY)
        assert manager.get_state() == SystemState.READY

    def test_warming_up_to_degraded(self) -> None:
        """Test WARMING_UP -> DEGRADED transition."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.WARMING_UP

        manager.set_state(SystemState.DEGRADED)
        assert manager.get_state() == SystemState.DEGRADED

    def test_ready_to_degraded(self) -> None:
        """Test READY -> DEGRADED transition."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.READY

        manager.set_state(SystemState.DEGRADED)
        assert manager.get_state() == SystemState.DEGRADED

    def test_degraded_to_ready(self) -> None:
        """Test DEGRADED -> READY transition."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.DEGRADED

        manager.set_state(SystemState.READY)
        assert manager.get_state() == SystemState.READY

    def test_ready_to_warming_up_allowed_for_retry(self) -> None:
        """READY -> WARMING_UP is valid to support warmup retry paths."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.READY

        manager.set_state(SystemState.WARMING_UP)
        assert manager.get_state() == SystemState.WARMING_UP

    def test_error_to_initializing(self) -> None:
        """Test ERROR -> INITIALIZING transition (restart)."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.ERROR

        manager.set_state(SystemState.INITIALIZING)
        assert manager.get_state() == SystemState.INITIALIZING

    def test_noop_transition_is_allowed(self) -> None:
        """Setting current state again must be a no-op, not an error."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.WARMING_UP

        manager.set_state(SystemState.WARMING_UP)
        assert manager.get_state() == SystemState.WARMING_UP

    def test_reset_sets_initializing_and_clears_report(self) -> None:
        """Reset should clear warmup report and return to INITIALIZING."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.DEGRADED
            manager._warmup_report["EURUSD"] = WarmupStatus(symbol="EURUSD")

        manager.reset()

        assert manager.get_state() == SystemState.INITIALIZING
        assert manager.get_warmup_report() == {}

    def test_reset_publishes_initializing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reset should publish INITIALIZING for multi-container retries."""
        manager = SystemStateManager()
        published: list[SystemState] = []
        monkeypatch.setattr(manager, "_publish_state", published.append)

        manager.reset()

        assert published == [SystemState.INITIALIZING]

    # ── P0-1: Invalid transition, same-state no-op, retry idempotency ──

    def test_invalid_transition_raises_value_error(self) -> None:
        """Invalid transition (e.g. INITIALIZING -> READY) must raise ValueError."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.INITIALIZING

        with pytest.raises(ValueError, match="Invalid state transition"):
            manager.set_state(SystemState.READY)

    @pytest.mark.parametrize("state", list(SystemState))
    def test_same_state_transition_is_noop_for_every_state(self, state: SystemState) -> None:
        """Every state must tolerate a same-state set_state() call silently."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = state

        manager.set_state(state)  # must NOT raise
        assert manager.get_state() == state

    def test_reset_is_idempotent(self) -> None:
        """Calling reset() multiple times must not raise or corrupt state."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.DEGRADED

        manager.reset()
        manager.reset()
        manager.reset()

        assert manager.get_state() == SystemState.INITIALIZING
        assert manager.get_warmup_report() == {}

    def test_reset_then_warmup_cycle_is_valid(self) -> None:
        """After reset, the full startup cycle must be reachable."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.ERROR

        manager.reset()
        assert manager.get_state() == SystemState.INITIALIZING

        manager.set_state(SystemState.WARMING_UP)
        assert manager.get_state() == SystemState.WARMING_UP

        manager.set_state(SystemState.READY)
        assert manager.get_state() == SystemState.READY

    @pytest.mark.parametrize(
        "from_state, to_state",
        [
            (SystemState.INITIALIZING, SystemState.READY),
            (SystemState.INITIALIZING, SystemState.DEGRADED),
            (SystemState.WARMING_UP, SystemState.INITIALIZING),
            (SystemState.READY, SystemState.INITIALIZING),
            (SystemState.DEGRADED, SystemState.INITIALIZING),
            (SystemState.ERROR, SystemState.READY),
            (SystemState.ERROR, SystemState.DEGRADED),
        ],
    )
    def test_all_invalid_transitions_raise(self, from_state: SystemState, to_state: SystemState) -> None:
        """Exhaustive check that disallowed transitions raise ValueError."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = from_state

        with pytest.raises(ValueError):
            manager.set_state(to_state)


class TestReadyCheck:
    """Test is_ready() check."""

    def test_ready_state_returns_true(self) -> None:
        """Test is_ready() returns True when state is READY."""
        manager = SystemStateManager()
        with manager._rw_lock:
            manager._state = SystemState.READY

        assert manager.is_ready() is True

    def test_non_ready_states_return_false(self) -> None:
        """Test is_ready() returns False for non-READY states."""
        manager = SystemStateManager()

        for state in [
            SystemState.INITIALIZING,
            SystemState.WARMING_UP,
            SystemState.DEGRADED,
            SystemState.ERROR,
        ]:
            with manager._rw_lock:
                manager._state = state
            assert manager.is_ready() is False


class TestTradeableCheck:
    """Test is_tradeable() per-symbol check."""

    def test_tradeable_when_complete_and_ready(self) -> None:
        """Test symbol is tradeable when COMPLETE and system READY."""
        manager = SystemStateManager()

        with manager._rw_lock:
            manager._state = SystemState.READY
            manager._warmup_report["EURUSD"] = WarmupStatus(
                symbol="EURUSD",
                W1_bars=25,
                D1_bars=60,
                H4_bars=15,
                H1_bars=60,
                status=SymbolStatus.COMPLETE,
            )

        assert manager.is_tradeable("EURUSD") is True

    def test_not_tradeable_when_incomplete(self) -> None:
        """Test symbol is not tradeable when INCOMPLETE_DATA."""
        manager = SystemStateManager()

        with manager._rw_lock:
            manager._state = SystemState.READY
            manager._warmup_report["EURUSD"] = WarmupStatus(
                symbol="EURUSD",
                W1_bars=10,  # Below min_bars
                D1_bars=30,
                H4_bars=5,
                H1_bars=25,
                status=SymbolStatus.INCOMPLETE_DATA,
            )

        assert manager.is_tradeable("EURUSD") is False

    def test_not_tradeable_when_system_warming_up(self) -> None:
        """Test symbol is not tradeable when system is WARMING_UP."""
        manager = SystemStateManager()

        with manager._rw_lock:
            manager._state = SystemState.WARMING_UP
            manager._warmup_report["EURUSD"] = WarmupStatus(
                symbol="EURUSD",
                status=SymbolStatus.COMPLETE,
            )

        assert manager.is_tradeable("EURUSD") is False

    def test_not_tradeable_when_symbol_not_in_report(self) -> None:
        """Test symbol is not tradeable when not in warmup report."""
        manager = SystemStateManager()

        with manager._rw_lock:
            manager._state = SystemState.READY

        assert manager.is_tradeable("UNKNOWN") is False


class TestWarmupValidation:
    """Test warmup validation."""

    def test_sufficient_bars_marked_complete(self) -> None:
        """Test symbols with sufficient bars are marked COMPLETE."""
        manager = SystemStateManager()

        results = {
            "EURUSD": {
                "W1": [{"bar": i} for i in range(25)],  # >= 20
                "D1": [{"bar": i} for i in range(60)],  # >= 50
                "H4": [{"bar": i} for i in range(15)],  # >= 10
                "H1": [{"bar": i} for i in range(60)],  # >= 50
            }
        }

        manager.validate_warmup(results)

        report = manager.get_warmup_report()
        assert "EURUSD" in report
        assert report["EURUSD"].status == SymbolStatus.COMPLETE
        assert report["EURUSD"].W1_bars == 25
        assert report["EURUSD"].D1_bars == 60
        assert report["EURUSD"].H4_bars == 15
        assert report["EURUSD"].H1_bars == 60

    def test_insufficient_bars_marked_incomplete(self) -> None:
        """Test symbols with insufficient bars are marked INCOMPLETE_DATA."""
        manager = SystemStateManager()

        results = {
            "EURUSD": {
                "W1": [{"bar": i} for i in range(10)],  # < 20
                "D1": [{"bar": i} for i in range(30)],  # < 50
                "H4": [{"bar": i} for i in range(5)],  # < 10
                "H1": [{"bar": i} for i in range(25)],  # < 50
            }
        }

        manager.validate_warmup(results)

        report = manager.get_warmup_report()
        assert "EURUSD" in report
        assert report["EURUSD"].status == SymbolStatus.INCOMPLETE_DATA

    def test_mixed_symbols(self) -> None:
        """Test validation with mix of complete and incomplete symbols."""
        manager = SystemStateManager()

        results = {
            "EURUSD": {
                "W1": [{"bar": i} for i in range(25)],
                "D1": [{"bar": i} for i in range(60)],
                "H4": [{"bar": i} for i in range(15)],
                "H1": [{"bar": i} for i in range(60)],
            },
            "GBPUSD": {
                "W1": [{"bar": i} for i in range(10)],
                "D1": [{"bar": i} for i in range(30)],
                "H4": [{"bar": i} for i in range(5)],
                "H1": [{"bar": i} for i in range(25)],
            },
        }

        manager.validate_warmup(results)

        report = manager.get_warmup_report()
        assert report["EURUSD"].status == SymbolStatus.COMPLETE
        assert report["GBPUSD"].status == SymbolStatus.INCOMPLETE_DATA


class TestSymbolDegradation:
    """Test symbol degradation and recovery."""

    def test_mark_symbol_degraded(self) -> None:
        """Test marking a symbol as degraded."""
        manager = SystemStateManager()

        with manager._rw_lock:
            manager._state = SystemState.READY
            manager._warmup_report["EURUSD"] = WarmupStatus(
                symbol="EURUSD",
                status=SymbolStatus.COMPLETE,
            )

        manager.mark_symbol_degraded("EURUSD", "Price drift 75 pips")

        report = manager.get_warmup_report()
        assert report["EURUSD"].status == SymbolStatus.DEGRADED

    def test_mark_symbol_recovered(self) -> None:
        """Test marking a symbol as recovered."""
        manager = SystemStateManager()

        with manager._rw_lock:
            manager._state = SystemState.DEGRADED
            manager._warmup_report["EURUSD"] = WarmupStatus(
                symbol="EURUSD",
                W1_bars=25,
                D1_bars=60,
                H4_bars=15,
                H1_bars=60,
                status=SymbolStatus.DEGRADED,
            )

        manager.mark_symbol_recovered("EURUSD")

        report = manager.get_warmup_report()
        assert report["EURUSD"].status == SymbolStatus.COMPLETE

    def test_system_degraded_when_all_symbols_degraded(self) -> None:
        """Test system transitions to DEGRADED when all symbols degraded."""
        manager = SystemStateManager()

        with manager._rw_lock:
            manager._state = SystemState.READY
            manager._warmup_report["EURUSD"] = WarmupStatus(
                symbol="EURUSD",
                status=SymbolStatus.COMPLETE,
            )

        manager.mark_symbol_degraded("EURUSD", "Test")

        # System should transition to DEGRADED
        assert manager.get_state() == SystemState.DEGRADED


class TestSingletonBehavior:
    """Test singleton pattern."""

    def test_singleton_returns_same_instance(self) -> None:
        """Test SystemStateManager returns same instance."""
        manager1 = SystemStateManager()
        manager2 = SystemStateManager()

        assert manager1 is manager2

    def test_singleton_shares_state(self) -> None:
        """Test singleton instances share state."""
        manager1 = SystemStateManager()
        manager2 = SystemStateManager()

        with manager1._rw_lock:
            manager1._warmup_report["TEST"] = WarmupStatus(
                symbol="TEST",
                status=SymbolStatus.COMPLETE,
            )

        report = manager2.get_warmup_report()
        assert "TEST" in report
