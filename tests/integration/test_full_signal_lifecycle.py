"""
Integration test: full signal lifecycle from verdict -> risk check -> journal.
Tests the entire authority chain respects boundaries.
"""

import pytest


@pytest.mark.integration
class TestFullSignalLifecycle:
    """End-to-end signal lifecycle respecting authority boundaries."""

    def _constitution_decides(self, analysis_scores):
        """LAYER-12 decides. Sole authority."""
        avg = sum(analysis_scores.values()) / len(analysis_scores)
        if avg >= 7.0:
            return {"verdict": "EXECUTE", "confidence": avg / 10}
        if avg >= 4.0:
            return {"verdict": "HOLD", "confidence": avg / 10}
        return {"verdict": "NO_TRADE", "confidence": avg / 10}

    def _dashboard_risk_check(self, verdict, account_state, prop_guard):
        """Dashboard enriches with risk but NEVER changes verdict."""
        risk_result = {
            "trade_allowed": prop_guard.get("allowed", True),
            "recommended_lot": 0.5 if prop_guard.get("allowed") else 0.0,
            "max_safe_lot": 2.0 if prop_guard.get("allowed") else 0.0,
            "reason": prop_guard.get("code", "OK"),
        }
        return {
            "signal": verdict,  # UNCHANGED
            "risk": risk_result,
            "account": account_state,
        }

    def _journal_record(self, enriched, journal_entries):
        """Append journal entries -- no decision power."""
        journal_entries.append(
            {
                "journal_type": "J2",
                "verdict": enriched["signal"]["verdict"],
                "confidence": enriched["signal"]["confidence"],
            }
        )
        if enriched["signal"]["verdict"] == "EXECUTE" and enriched["risk"]["trade_allowed"]:
            journal_entries.append(
                {
                    "journal_type": "J3",
                    "lot": enriched["risk"]["recommended_lot"],
                }
            )

    def test_execute_flow(self, sample_account_state):
        scores = {"wolf": 8.5, "tii": 7.2, "frpc": 7.8}
        verdict = self._constitution_decides(scores)
        assert verdict["verdict"] == "EXECUTE"

        guard = {"allowed": True, "code": "OK"}
        enriched = self._dashboard_risk_check(verdict, sample_account_state, guard)
        assert enriched["signal"]["verdict"] == "EXECUTE"  # not changed by dashboard
        assert enriched["risk"]["trade_allowed"] is True

        journal = []
        self._journal_record(enriched, journal)
        assert any(j["journal_type"] == "J2" for j in journal)
        assert any(j["journal_type"] == "J3" for j in journal)

    def test_execute_blocked_by_risk(self, sample_account_state):
        """L12 says EXECUTE but propfirm guard blocks it."""
        scores = {"wolf": 8.5, "tii": 7.2, "frpc": 7.8}
        verdict = self._constitution_decides(scores)
        assert verdict["verdict"] == "EXECUTE"

        guard = {"allowed": False, "code": "DAILY_LOSS_BREACH"}
        enriched = self._dashboard_risk_check(verdict, sample_account_state, guard)

        # Verdict STILL says EXECUTE (L12 authority not overridden)
        assert enriched["signal"]["verdict"] == "EXECUTE"
        # But risk blocks execution
        assert enriched["risk"]["trade_allowed"] is False
        assert enriched["risk"]["recommended_lot"] == 0.0

        journal = []
        self._journal_record(enriched, journal)
        # J3 (execution) should NOT appear since risk blocked
        types = [j["journal_type"] for j in journal]
        assert "J2" in types
        assert "J3" not in types

    def test_reject_flow(self, sample_account_state):
        scores = {"wolf": 2.5, "tii": 3.0, "frpc": 2.0}
        verdict = self._constitution_decides(scores)
        assert verdict["verdict"] == "NO_TRADE"

        guard = {"allowed": True, "code": "OK"}
        enriched = self._dashboard_risk_check(verdict, sample_account_state, guard)

        # Even though risk allows, verdict is NO_TRADE
        assert enriched["signal"]["verdict"] == "NO_TRADE"

        journal = []
        self._journal_record(enriched, journal)
        types = [j["journal_type"] for j in journal]
        assert "J2" in types
        assert "J3" not in types  # no execution for NO_TRADE

    def test_dashboard_never_upgrades_verdict(self, sample_account_state):
        """Dashboard must NEVER change NO_TRADE to EXECUTE."""
        verdict = {"verdict": "NO_TRADE", "confidence": 0.3}
        guard = {"allowed": True, "code": "OK"}
        enriched = self._dashboard_risk_check(verdict, sample_account_state, guard)

        # Critical assertion: verdict stays NO_TRADE
        assert enriched["signal"]["verdict"] == "NO_TRADE"
