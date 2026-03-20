"""
Regression tests for the configurable stale grace period in assess_governance().

Verifies that:
1. When WOLF_GOVERNANCE_STALE_GRACE_SEC=0 (default), stale_preserved → HOLD (existing behavior).
2. When WOLF_GOVERNANCE_STALE_GRACE_SEC>0, stale_preserved data below the grace threshold
   produces ALLOW_REDUCED with a 0.20 penalty instead of HOLD.
3. stale_preserved data older than the grace threshold still produces HOLD.
4. The WS warmup grace path is unaffected.

Note: FeedFreshness classifies data as stale_preserved when staleness > 300 seconds
(WOLF_STALE_THRESHOLD_SECONDS default). Tests use 400-second staleness to reliably
enter stale_preserved state while staying below HARD_STALE_THRESHOLD_SEC (600 s).
"""

from __future__ import annotations

import time

import pytest

from state.governance_gate import (
    GovernanceAction,
    assess_governance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Staleness value (seconds) that triggers stale_preserved:
# > stale_threshold (300 s default) but < HARD_STALE_THRESHOLD_SEC (600 s)
_STALE_PRESERVED_AGE = 400.0


def _now() -> float:
    return time.time()


def _stale_last_seen(staleness_seconds: float, now: float) -> float:
    """Return a last_seen_ts that is staleness_seconds old relative to now."""
    return now - staleness_seconds


# ---------------------------------------------------------------------------
# Tests — default behavior (STALE_GRACE_SEC=0, no grace)
# ---------------------------------------------------------------------------


class TestStalePoliciesNoGrace:
    """Stale grace disabled (default) — stale_preserved always produces HOLD."""

    def test_stale_preserved_produces_hold_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no stale grace env var, stale_preserved → HOLD."""
        import state.governance_gate as gg

        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 0.0)

        now = _now()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            ws_connected_at=None,
            now_ts=now,
        )

        assert verdict.action == GovernanceAction.HOLD

    def test_stale_preserved_hold_reason_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no grace, stale_preserved_hold or stale_preserved appears in reasons."""
        import state.governance_gate as gg

        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 0.0)

        now = _now()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            ws_connected_at=None,
            now_ts=now,
        )

        reason_str = " ".join(verdict.reasons)
        assert "stale" in reason_str


# ---------------------------------------------------------------------------
# Tests — stale grace enabled
# ---------------------------------------------------------------------------


class TestStalePoliciesWithGrace:
    """With STALE_GRACE_SEC>0, stale_preserved below grace threshold → ALLOW_REDUCED."""

    def test_below_grace_produces_allow_reduced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Staleness <= STALE_GRACE_SEC produces ALLOW_REDUCED instead of HOLD."""
        import state.governance_gate as gg

        # Grace window is 500 s; data is 400 s stale → within grace
        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 500.0)

        now = _now()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            ws_connected_at=None,
            now_ts=now,
        )

        assert verdict.action == GovernanceAction.ALLOW_REDUCED

    def test_below_grace_penalty_is_at_least_0_20(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The stale grace path adds 0.20 to the confidence penalty."""
        import state.governance_gate as gg

        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 500.0)

        now = _now()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            ws_connected_at=None,
            now_ts=now,
        )

        # stale_preserved adds 0.15 baseline + 0.20 grace penalty = 0.35
        assert verdict.confidence_penalty >= 0.20

    def test_below_grace_reason_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stale_grace reason is recorded in the verdict reasons tuple."""
        import state.governance_gate as gg

        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 500.0)

        now = _now()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            ws_connected_at=None,
            now_ts=now,
        )

        reason_str = " ".join(verdict.reasons)
        assert "stale_grace" in reason_str

    def test_above_grace_still_produces_hold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Staleness > STALE_GRACE_SEC still produces HOLD."""
        import state.governance_gate as gg

        # Grace window is 300 s; data is 400 s stale → beyond grace
        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 300.0)

        now = _now()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            ws_connected_at=None,
            now_ts=now,
        )

        assert verdict.action == GovernanceAction.HOLD

    def test_exactly_at_grace_boundary_allows_reduced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Staleness exactly equal to grace threshold is within grace window (<=)."""
        import state.governance_gate as gg

        # Grace window exactly equals staleness → should ALLOW_REDUCED
        monkeypatch.setattr(gg, "STALE_GRACE_SEC", _STALE_PRESERVED_AGE)

        now = _now()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            ws_connected_at=None,
            now_ts=now,
        )

        assert verdict.action == GovernanceAction.ALLOW_REDUCED

    def test_ws_warmup_grace_takes_precedence_over_stale_grace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WS warmup grace path fires before stale grace check."""
        import state.governance_gate as gg

        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 500.0)
        monkeypatch.setattr(gg, "WS_WARMUP_GRACE_SEC", 300.0)

        now = _now()
        ws_connected_at = now - 10.0  # WS connected 10 seconds ago

        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            ws_connected_at=ws_connected_at,
            now_ts=now,
        )

        # WS warmup path takes precedence — reason should mention ws_warmup_grace
        assert verdict.action == GovernanceAction.ALLOW_REDUCED
        reason_str = " ".join(verdict.reasons)
        assert "ws_warmup_grace" in reason_str

    def test_kill_switch_overrides_stale_grace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kill-switch always produces BLOCK regardless of stale grace setting."""
        import state.governance_gate as gg

        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 500.0)

        now = _now()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            kill_switch_value="1",
            now_ts=now,
        )

        assert verdict.action == GovernanceAction.BLOCK

    def test_no_producer_overrides_stale_grace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """no_producer state overrides stale grace — feed cannot be proven."""
        import state.governance_gate as gg

        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 500.0)

        now = _now()
        # last_seen_ts=None → no_producer
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=None,
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            now_ts=now,
        )

        assert verdict.action == GovernanceAction.HOLD

    def test_stale_grace_penalty_capped_at_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confidence penalty is capped at 1.0 even with additional DQ penalty."""
        import state.governance_gate as gg

        monkeypatch.setattr(gg, "STALE_GRACE_SEC", 500.0)

        now = _now()
        # dq_penalty=0.80 + stale_preserved base 0.15 + grace 0.20 would exceed 1.0
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=_stale_last_seen(_STALE_PRESERVED_AGE, now),
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            dq_penalty=0.80,
            now_ts=now,
        )

        assert verdict.confidence_penalty <= 1.0


# ---------------------------------------------------------------------------
# Tests — env-var wiring
# ---------------------------------------------------------------------------


class TestStaleGraceEnvConfig:
    """Verify WOLF_GOVERNANCE_STALE_GRACE_SEC env variable is consumed correctly."""

    def test_env_var_sets_stale_grace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STALE_GRACE_SEC module-level constant loads from env var."""
        monkeypatch.setenv("WOLF_GOVERNANCE_STALE_GRACE_SEC", "90")

        # Re-import to pick up env-var changes (test isolation)
        import importlib

        import state.governance_gate as gg

        importlib.reload(gg)
        assert pytest.approx(90.0) == gg.STALE_GRACE_SEC

    def test_env_var_zero_disables_grace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WOLF_GOVERNANCE_STALE_GRACE_SEC=0 disables the stale grace path."""
        monkeypatch.setenv("WOLF_GOVERNANCE_STALE_GRACE_SEC", "0")

        import importlib

        import state.governance_gate as gg

        importlib.reload(gg)
        assert pytest.approx(0.0) == gg.STALE_GRACE_SEC

    def test_invalid_env_var_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-numeric env var falls back to default (0.0)."""
        monkeypatch.setenv("WOLF_GOVERNANCE_STALE_GRACE_SEC", "notanumber")

        import importlib

        import state.governance_gate as gg

        importlib.reload(gg)
        assert pytest.approx(0.0) == gg.STALE_GRACE_SEC
