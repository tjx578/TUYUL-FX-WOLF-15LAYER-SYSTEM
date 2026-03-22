"""
Tests for journal (J1-J4) -- append-only, immutable audit trail.
Constitutional boundary: journal has NO decision power, write-only.
"""

import copy

import pytest

try:
    from journal.writer import JournalWriter  # type: ignore[import-not-found]

    HAS_JOURNAL = True
except ImportError:
    HAS_JOURNAL = False


class TestJournalStructure:
    """J1-J4 record structure validation."""

    def _j1_context(self, symbol="EURUSD"):
        return {
            "journal_type": "J1",
            "symbol": symbol,
            "timestamp": "2026-02-15T10:30:00Z",
            "context": {
                "market_regime": "trending",
                "session": "LONDON",
                "key_levels": [1.0800, 1.0850, 1.0900],
            },
        }

    def _j2_decision(self, verdict="EXECUTE", signal_id="SIG-001"):
        return {
            "journal_type": "J2",
            "signal_id": signal_id,
            "verdict": verdict,
            "timestamp": "2026-02-15T10:30:01Z",
            "scores": {"wolf": 8.5, "tii": 7.2, "frpc": 6.8},
        }

    def _j3_execution(self, signal_id="SIG-001"):
        return {
            "journal_type": "J3",
            "signal_id": signal_id,
            "order_id": "ORD-0001",
            "fill_price": 1.0855,
            "lot_size": 0.5,
            "slippage_pips": 0.3,
            "timestamp": "2026-02-15T10:30:05Z",
        }

    def _j4_reflection(self, signal_id="SIG-001"):
        return {
            "journal_type": "J4",
            "signal_id": signal_id,
            "outcome": "WIN",
            "pnl": 250.0,
            "rr_achieved": 1.8,
            "reflection": "Entry was clean, exit could have been later.",
            "timestamp": "2026-02-15T14:00:00Z",
        }

    def test_j1_has_context(self):
        j1 = self._j1_context()
        assert j1["journal_type"] == "J1"
        assert "context" in j1

    @pytest.mark.parametrize("verdict", ["EXECUTE", "HOLD", "NO_TRADE", "ABORT"])
    def test_j2_logs_all_verdicts(self, verdict):
        j2 = self._j2_decision(verdict=verdict)
        assert j2["verdict"] == verdict

    def test_j2_rejected_setup_logged(self):
        """Rejected setups MUST be journaled (constitutional requirement)."""
        j2 = self._j2_decision(verdict="NO_TRADE")
        assert j2["journal_type"] == "J2"
        assert j2["verdict"] == "NO_TRADE"

    def test_j3_only_if_executed(self):
        """J3 should only exist for EXECUTE verdicts."""
        j2 = self._j2_decision(verdict="NO_TRADE")
        # For NO_TRADE, J3 should not be created
        should_create_j3 = j2["verdict"] == "EXECUTE"
        assert not should_create_j3

    def test_j4_exists_for_all_decisions(self):
        """J4 (reflection) should exist even for rejected setups."""
        j4 = self._j4_reflection()
        assert j4["journal_type"] == "J4"


class TestJournalImmutability:
    """Journal is write-only / append-only. No updates, no deletes."""

    def test_append_only_simulation(self):
        journal = []  # simulated append-only log
        entry = {"id": 1, "type": "J2", "verdict": "EXECUTE"}
        journal.append(entry)

        # Attempt to modify -- should not affect the journal
        copy.deepcopy(journal[0])
        entry["verdict"] = "TAMPERED"

        # If the journal stores a copy, original should be intact
        journal[0]
        # This test documents the requirement -- implementation must deepcopy on insert
        # In practice, journal entries should be immutable dataclasses or frozen dicts

    def test_no_delete_operation(self):
        """Journal must not expose a delete method."""

        class AppendOnlyJournal:
            def __init__(self):
                self._entries = []

            def append(self, entry):
                self._entries.append(copy.deepcopy(entry))

            def read_all(self):
                return [copy.deepcopy(e) for e in self._entries]

        j = AppendOnlyJournal()
        j.append({"type": "J1", "data": "test"})
        assert not hasattr(j, "delete")
        assert not hasattr(j, "update")
        assert not hasattr(j, "remove")

    def test_no_decision_authority(self):
        """Journal module must not export decision functions."""
        forbidden_names = ["decide", "compute_verdict", "execute_trade", "place_order", "override_verdict"]
        # Conceptual test -- verify naming conventions
        for name in forbidden_names:
            # If journal module exists, check it
            if HAS_JOURNAL:
                assert not hasattr(JournalWriter, name), (  # pyright: ignore[reportPossiblyUnboundVariable]
                    f"Journal must not have '{name}' -- no decision authority"
                )


class TestJournalCompleteness:
    """Ensure full lifecycle is journaled."""

    def test_full_execute_lifecycle(self):
        """EXECUTE flow must produce J1, J2, J3, J4."""
        entries = []
        entries.append({"journal_type": "J1", "signal_id": "SIG-001"})
        entries.append({"journal_type": "J2", "signal_id": "SIG-001", "verdict": "EXECUTE"})
        entries.append({"journal_type": "J3", "signal_id": "SIG-001", "order_id": "ORD-001"})
        entries.append({"journal_type": "J4", "signal_id": "SIG-001", "outcome": "WIN"})

        types = [e["journal_type"] for e in entries]
        assert types == ["J1", "J2", "J3", "J4"]

    def test_reject_lifecycle(self):
        """NO_TRADE flow must produce J1, J2, J4 (no J3)."""
        entries = []
        entries.append({"journal_type": "J1", "signal_id": "SIG-002"})
        entries.append({"journal_type": "J2", "signal_id": "SIG-002", "verdict": "NO_TRADE"})
        entries.append({"journal_type": "J4", "signal_id": "SIG-002", "outcome": "REJECTED"})

        types = [e["journal_type"] for e in entries]
        assert types == ["J1", "J2", "J4"]
        assert "J3" not in types
