"""Tests for dashboard/state_manager.py — RWLock, init, deep copy."""
from __future__ import annotations

import threading
import time

from dashboard.rwlock import RWLock
from dashboard.state_manager import SignalState, StateManager


class TestRWLock:
    """Tests for the Read-Write Lock implementation."""

    def test_multiple_concurrent_readers(self) -> None:
        """Multiple readers should not block each other."""
        lock = RWLock()
        results: list[int] = []
        barrier = threading.Barrier(3)

        def reader(reader_id: int) -> None:
            with lock.read():
                barrier.wait(timeout=2.0)  # All readers must reach here concurrently
                results.append(reader_id)

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(results) == 3

    def test_writer_excludes_readers(self) -> None:
        """Writer should block readers and vice versa."""
        lock = RWLock()
        sequence: list[str] = []
        writer_entered = threading.Event()
        writer_done = threading.Event()

        def writer() -> None:
            with lock.write():
                writer_entered.set()
                sequence.append("writer_start")
                time.sleep(0.1)
                sequence.append("writer_end")
                writer_done.set()

        def reader() -> None:
            writer_entered.wait(timeout=2.0)
            # Small delay to ensure reader tries to acquire after writer holds lock
            time.sleep(0.02)
            with lock.read():
                sequence.append("reader")

        t_w = threading.Thread(target=writer)
        t_r = threading.Thread(target=reader)
        t_w.start()
        t_r.start()
        t_w.join(timeout=5.0)
        t_r.join(timeout=5.0)

        # Reader should come after writer_end
        assert sequence.index("reader") > sequence.index("writer_end")

    def test_write_excludes_write(self) -> None:
        """Only one writer at a time."""
        lock = RWLock()
        active_writers: list[int] = []
        max_concurrent = [0]
        lock_for_counter = threading.Lock()

        def writer() -> None:
            with lock.write():
                with lock_for_counter:
                    active_writers.append(1)
                    current = sum(active_writers)
                    if current > max_concurrent[0]:
                        max_concurrent[0] = current
                time.sleep(0.02)
                with lock_for_counter:
                    active_writers.pop()

        threads = [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert max_concurrent[0] == 1


class TestStateManagerInit:
    """Verify all attributes initialized in __init__ — no hasattr lazy init."""

    def test_all_attributes_exist_after_init(self) -> None:
        """All internal state should exist immediately, not lazily."""
        sm = StateManager()

        # These should all exist without any method call first
        assert hasattr(sm, "_account_state")
        assert hasattr(sm, "_signals")
        assert hasattr(sm, "_risk_overrides")
        assert hasattr(sm, "_last_heartbeat")
        assert hasattr(sm, "_metadata")
        assert hasattr(sm, "_lock")

    def test_account_state_defaults(self) -> None:
        sm = StateManager()
        state = sm.get_account_state()
        assert state.balance == 0.0
        assert state.equity == 0.0
        assert state.open_positions == 0

    def test_snapshot_works_without_prior_updates(self) -> None:
        """snapshot() should work on a freshly initialized StateManager."""
        sm = StateManager()
        snap = sm.snapshot()
        assert "account" in snap
        assert "signals" in snap
        assert "risk_overrides" in snap
        assert snap["account"]["balance"] == 0.0


class TestDeepCopy:
    """Verify snapshot and getters return deep copies — mutation isolation."""

    def test_snapshot_mutation_does_not_affect_internal_state(self) -> None:
        sm = StateManager()
        sm.update_account_state(balance=10000.0, equity=10500.0)

        snap1 = sm.snapshot()
        # Mutate the snapshot
        snap1["account"]["balance"] = 999999.0
        snap1["risk_overrides"]["injected"] = True
        snap1["signals"]["fake"] = {"injected": True}

        # Internal state should be unaffected
        snap2 = sm.snapshot()
        assert snap2["account"]["balance"] == 10000.0
        assert "injected" not in snap2["risk_overrides"]
        assert "fake" not in snap2["signals"]

    def test_get_account_state_returns_copy(self) -> None:
        sm = StateManager()
        sm.update_account_state(balance=5000.0)

        state1 = sm.get_account_state()
        state1.balance = 999999.0

        state2 = sm.get_account_state()
        assert state2.balance == 5000.0

    def test_get_signal_returns_copy(self) -> None:
        sm = StateManager()
        signal = SignalState(
            signal_id="sig_001",
            symbol="EURUSD",
            verdict="EXECUTE",
            confidence=0.85,
            metadata={"layer_scores": {"wolf": 8.5}},
        )
        sm.register_signal(signal)

        retrieved = sm.get_signal("sig_001")
        assert retrieved is not None
        retrieved.metadata["injected"] = True
        retrieved.status = "CORRUPTED"

        original = sm.get_signal("sig_001")
        assert original is not None
        assert "injected" not in original.metadata
        assert original.status != "CORRUPTED"

    def test_get_active_signals_returns_copies(self) -> None:
        sm = StateManager()
        sm.register_signal(
            SignalState(
                signal_id="sig_a",
                symbol="EURUSD",
                verdict="EXECUTE",
                confidence=0.9,
            )
        )
        sm.register_signal(
            SignalState(
                signal_id="sig_b",
                symbol="GBPUSD",
                verdict="HOLD",
                confidence=0.6,
            )
        )

        actives = sm.get_active_signals()
        assert len(actives) == 2

        # Mutate returned copies
        for s in actives:
            s.confidence = 0.0
            s.metadata["hacked"] = True

        # Originals intact
        for s in sm.get_active_signals():
            assert s.confidence > 0
            assert "hacked" not in s.metadata

    def test_get_risk_overrides_returns_copy(self) -> None:
        sm = StateManager()
        sm.set_risk_override("max_lot", 0.5)

        overrides = sm.get_risk_overrides()
        overrides["max_lot"] = 999.0
        overrides["injected"] = True

        clean = sm.get_risk_overrides()
        assert clean["max_lot"] == 0.5
        assert "injected" not in clean


class TestAccountStateUpdates:
    def test_partial_update(self) -> None:
        sm = StateManager()
        sm.update_account_state(balance=10000.0)
        sm.update_account_state(equity=10500.0)

        state = sm.get_account_state()
        assert state.balance == 10000.0
        assert state.equity == 10500.0

    def test_updated_at_timestamp(self) -> None:
        sm = StateManager()
        before = time.time()
        sm.update_account_state(balance=5000.0)
        after = time.time()

        state = sm.get_account_state()
        assert before <= state.updated_at <= after


class TestSignalLifecycle:
    def test_register_and_retrieve(self) -> None:
        sm = StateManager()
        sm.register_signal(
            SignalState(
                signal_id="sig_001",
                symbol="EURUSD",
                verdict="EXECUTE",
                confidence=0.88,
            )
        )
        sig = sm.get_signal("sig_001")
        assert sig is not None
        assert sig.symbol == "EURUSD"
        assert sig.status == "SIGNAL_CREATED"

    def test_update_status(self) -> None:
        sm = StateManager()
        sm.register_signal(
            SignalState(
                signal_id="sig_001",
                symbol="EURUSD",
                verdict="EXECUTE",
                confidence=0.88,
            )
        )
        assert sm.update_signal_status("sig_001", "PENDING_PLACED") is True
        sig = sm.get_signal("sig_001")
        assert sig is not None
        assert sig.status == "PENDING_PLACED"

    def test_update_nonexistent_signal(self) -> None:
        sm = StateManager()
        assert sm.update_signal_status("nonexistent", "TRADE_CLOSED") is False

    def test_get_active_signals_excludes_terminal(self) -> None:
        sm = StateManager()
        sm.register_signal(
            SignalState(
                signal_id="s1",
                symbol="EURUSD",
                verdict="EXECUTE",
                confidence=0.9,
            )
        )
        sm.register_signal(
            SignalState(
                signal_id="s2",
                symbol="GBPUSD",
                verdict="HOLD",
                confidence=0.5,
            )
        )
        sm.update_signal_status("s2", "TRADE_CLOSED")

        active = sm.get_active_signals()
        assert len(active) == 1
        assert active[0].signal_id == "s1"

    def test_get_signal_not_found(self) -> None:
        sm = StateManager()
        assert sm.get_signal("nonexistent") is None


class TestConcurrentAccess:
    """Verify RWLock integration under concurrent read/write pressure."""

    def test_concurrent_reads_and_writes(self) -> None:
        sm = StateManager()
        sm.update_account_state(balance=10000.0, equity=10000.0)
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for i in range(200):
                    sm.update_account_state(
                        balance=10000.0 + i,
                        equity=10000.0 + i * 0.5,
                    )
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(200):
                    snap = sm.snapshot()
                    # Verify consistency: snapshot should have valid structure
                    assert "account" in snap
                    assert isinstance(snap["account"]["balance"], float)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(2)] + [
            threading.Thread(target=reader) for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        assert len(errors) == 0


class TestReset:
    def test_reset_clears_all(self) -> None:
        sm = StateManager()
        sm.update_account_state(balance=50000.0)
        sm.register_signal(
            SignalState(
                signal_id="s1",
                symbol="EURUSD",
                verdict="EXECUTE",
                confidence=0.9,
            )
        )
        sm.set_risk_override("max_lot", 1.0)
        sm.heartbeat()

        sm.reset()

        state = sm.get_account_state()
        assert state.balance == 0.0
        assert sm.get_signal("s1") is None
        assert sm.get_risk_overrides() == {}
        assert sm.get_last_heartbeat() == 0.0
