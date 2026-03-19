"""P0 regression tests — covers all P0 backlog items end-to-end.

These tests ensure the core P0 safety behaviors remain stable across
redeploys: state machine safety, heartbeat detection, freshness
classification, readiness semantics, and governance hold enforcement.
"""

from __future__ import annotations

import time

import orjson
import pytest

from context.system_state import SystemState, SystemStateManager
from state.data_freshness import (
    FRESHNESS_LIVE_MAX_AGE_SEC,
    FreshnessClass,
    classify_feed_freshness,
    stale_threshold_seconds,
)
from state.governance_gate import GovernanceAction, assess_governance

# ---------------------------------------------------------------------------
# P0-1: State machine transitions
# ---------------------------------------------------------------------------


class TestP0_1_StateMachineRegression:  # noqa: N801
    """Ingest state machine must not crash-loop on invalid transitions."""

    def setup_method(self):
        mgr = SystemStateManager()
        mgr.reset()

    def test_no_live_enum_value(self):
        """SystemState must NOT have a 'LIVE' value (historical bug)."""
        values = {s.value for s in SystemState}
        assert "LIVE" not in values

    def test_same_state_noop(self):
        mgr = SystemStateManager()
        mgr.set_state(SystemState.INITIALIZING)
        mgr.set_state(SystemState.INITIALIZING)  # must not raise
        assert mgr.get_state() == SystemState.INITIALIZING

    def test_reset_idempotent(self):
        mgr = SystemStateManager()
        mgr.set_state(SystemState.WARMING_UP)
        mgr.reset()
        mgr.reset()  # double reset must not raise
        assert mgr.get_state() == SystemState.INITIALIZING

    @pytest.mark.parametrize(
        "bad_from,bad_to",
        [
            (SystemState.INITIALIZING, SystemState.READY),
            (SystemState.INITIALIZING, SystemState.DEGRADED),
            (SystemState.WARMING_UP, SystemState.INITIALIZING),
        ],
    )
    def test_invalid_transitions_raise(self, bad_from, bad_to):
        mgr = SystemStateManager()
        if bad_from != SystemState.INITIALIZING:
            # Navigate to bad_from first
            if bad_from == SystemState.WARMING_UP:
                mgr.set_state(SystemState.WARMING_UP)
            elif bad_from == SystemState.READY:
                mgr.set_state(SystemState.WARMING_UP)
                mgr.set_state(SystemState.READY)
        with pytest.raises(ValueError):
            mgr.set_state(bad_to)


# ---------------------------------------------------------------------------
# P0-2: Heartbeat key alignment
# ---------------------------------------------------------------------------


class TestP0_2_HeartbeatKey:  # noqa: N801
    """Ingest must write to the canonical heartbeat key from redis_keys."""

    def test_ingest_uses_canonical_key(self):
        # The ingest module must use the centralized key
        import ingest_service
        from state.redis_keys import HEARTBEAT_INGEST

        assert ingest_service._PRODUCER_HEARTBEAT_KEY == HEARTBEAT_INGEST

    def test_pipeline_parses_json_heartbeat_payload(self):
        from pipeline.wolf_constitutional_pipeline import _parse_heartbeat_timestamp

        raw = orjson.dumps({"producer": "finnhub_ws", "ts": 1742378400.123})

        assert _parse_heartbeat_timestamp(raw) == pytest.approx(1742378400.123)


# ---------------------------------------------------------------------------
# P0-3: last_seen_ts instead of short TTL
# ---------------------------------------------------------------------------


class TestP0_3_LastSeenTs:  # noqa: N801
    """Freshness must be based on timestamp, not key TTL."""

    def test_ttl_is_housekeeping_only(self):
        from state.redis_keys import LATEST_TICK_TTL_SECONDS

        # TTL must be long (housekeeping, e.g. 86400s), not used for freshness
        assert LATEST_TICK_TTL_SECONDS >= 86400


# ---------------------------------------------------------------------------
# P0-4: Unified freshness classes
# ---------------------------------------------------------------------------


class TestP0_4_FreshnessClassUnification:  # noqa: N801
    """All modules must agree on the approved freshness classes."""

    def test_approved_classes_exist(self):
        expected = {"LIVE", "DEGRADED_BUT_REFRESHING", "STALE_PRESERVED", "NO_PRODUCER", "NO_TRANSPORT", "CONFIG_ERROR"}
        assert {c.value for c in FreshnessClass} == expected

    def test_live_boundary(self):
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=FRESHNESS_LIVE_MAX_AGE_SEC,
        )
        assert snap.freshness_class == FreshnessClass.LIVE

    def test_degraded_just_past_live(self):
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=FRESHNESS_LIVE_MAX_AGE_SEC + 0.1,
        )
        assert snap.freshness_class == FreshnessClass.DEGRADED_BUT_REFRESHING

    def test_stale_preserved_past_threshold(self):
        threshold = stale_threshold_seconds()
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=threshold + 1.0,
        )
        assert snap.freshness_class == FreshnessClass.STALE_PRESERVED

    def test_live_context_bus_uses_freshness_class(self):
        from context.live_context_bus import LiveContextBus

        LiveContextBus.reset_singleton()
        bus = LiveContextBus()
        bus.update_tick({"symbol": "EURUSD", "bid": 1.08, "ask": 1.09, "timestamp": time.time()})
        assert bus.get_feed_status("EURUSD") == "LIVE"
        assert bus.get_feed_status("NOPAIR") == "NO_PRODUCER"

    def test_data_feed_health_uses_central_threshold(self):
        from analysis.data_feed import FeedHealth, FeedStatus

        health = FeedHealth(
            status=FeedStatus.CONNECTED,
            last_tick_time=time.time(),
            latency_ms=5.0,
            staleness_seconds=FRESHNESS_LIVE_MAX_AGE_SEC - 1.0,
        )
        assert health.is_healthy is True

        stale_health = FeedHealth(
            status=FeedStatus.CONNECTED,
            last_tick_time=time.time(),
            latency_ms=5.0,
            staleness_seconds=FRESHNESS_LIVE_MAX_AGE_SEC + 1.0,
        )
        assert stale_health.is_healthy is False


# ---------------------------------------------------------------------------
# P0-5: Readiness freshness-aware
# ---------------------------------------------------------------------------


class TestP0_5_ReadinessEndpoint:  # noqa: N801
    """readyz must exist and be separate from healthz."""

    def test_readyz_route_registered(self):
        """The factory must register a /readyz route distinct from /healthz."""
        from unittest.mock import MagicMock, patch

        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        mock_redis.ping.return_value = True
        mock_redis.client = mock_redis

        with patch("storage.redis_client.RedisClient.__new__", return_value=mock_redis):
            from api.app_factory import create_app

            app = create_app()

        paths = {getattr(r, "path", None) for r in app.routes}
        assert "/readyz" in paths
        assert "/healthz" in paths


# ---------------------------------------------------------------------------
# P0-6: Governance hold under stale/no-producer
# ---------------------------------------------------------------------------


class TestP0_6_GovernanceHold:  # noqa: N801
    """Stale-preserved and no-producer must force HOLD, not ALLOW_REDUCED."""

    def test_no_producer_forces_hold_even_with_alive_heartbeat(self):
        now = time.time()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=None,  # no tick data
            transport_ok=True,
            heartbeat_ts=now - 5.0,  # heartbeat alive
            warmup_ready=True,
            now_ts=now,
        )
        assert verdict.action == GovernanceAction.HOLD

    def test_no_transport_forces_hold(self):
        verdict = assess_governance(
            symbol="EURUSD",
            transport_ok=False,
            warmup_ready=True,
        )
        assert verdict.action == GovernanceAction.HOLD

    def test_stale_preserved_forces_hold(self):
        """Data beyond stale threshold must HOLD — not silently trade."""
        now = time.time()
        threshold = stale_threshold_seconds()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=now - threshold - 10.0,  # beyond stale threshold
            transport_ok=True,
            heartbeat_ts=now - 5.0,
            warmup_ready=True,
            now_ts=now,
        )
        assert verdict.action == GovernanceAction.HOLD

    def test_stale_preserved_holds_even_with_fresh_heartbeat(self):
        """Fresh producer heartbeat must not override stale_preserved HOLD policy."""
        now = time.time()
        threshold = stale_threshold_seconds()

        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=now - threshold - 30.0,
            transport_ok=True,
            heartbeat_ts=now - 1.0,
            warmup_ready=True,
            now_ts=now,
        )

        assert verdict.action == GovernanceAction.HOLD
        assert any("stale_preserved" in reason for reason in verdict.reasons)

    def test_fresh_data_allows(self):
        now = time.time()
        verdict = assess_governance(
            symbol="EURUSD",
            last_seen_ts=now - 5.0,
            transport_ok=True,
            heartbeat_ts=now - 2.0,
            warmup_ready=True,
            now_ts=now,
        )
        assert verdict.action in (GovernanceAction.ALLOW, GovernanceAction.ALLOW_REDUCED)

    def test_execution_guard_blocks_stale(self):
        """ExecutionGuard must block when freshness severity is HIGH or CRITICAL."""
        from execution.execution_guard import ExecutionGuard

        guard = ExecutionGuard()
        guard.set_freshness_severity_provider(lambda _sym: "HIGH")
        result = guard.execute("sig-1", "acct-1", symbol="EURUSD")
        assert not result.allowed
        assert result.code == "FEED_FRESHNESS_BLOCK"

    def test_execution_guard_blocks_no_producer(self):
        from execution.execution_guard import ExecutionGuard

        guard = ExecutionGuard()
        guard.set_freshness_severity_provider(lambda _sym: "CRITICAL")
        result = guard.execute("sig-1", "acct-1", symbol="EURUSD")
        assert not result.allowed
        assert result.code == "FEED_FRESHNESS_BLOCK"

    def test_execution_guard_allows_live(self):
        from execution.execution_guard import ExecutionGuard

        guard = ExecutionGuard()
        guard.set_freshness_severity_provider(lambda _sym: "LOW")
        result = guard.execute("sig-1", "acct-1", symbol="EURUSD")
        assert result.allowed


# ---------------------------------------------------------------------------
# Cross-cutting: freshness class transition completeness
# ---------------------------------------------------------------------------


class TestFreshnessClassTransitions:
    """Verify all approved classes are reachable via classify_feed_freshness."""

    def test_all_classes_reachable(self):
        reached: set[FreshnessClass] = set()

        # LIVE
        snap = classify_feed_freshness(transport_ok=True, has_producer_signal=True, staleness_seconds=1.0)
        reached.add(snap.freshness_class)

        # DEGRADED_BUT_REFRESHING
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=FRESHNESS_LIVE_MAX_AGE_SEC + 10.0,
        )
        reached.add(snap.freshness_class)

        # STALE_PRESERVED
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=stale_threshold_seconds() + 10.0,
        )
        reached.add(snap.freshness_class)

        # NO_PRODUCER
        snap = classify_feed_freshness(transport_ok=True, has_producer_signal=False)
        reached.add(snap.freshness_class)

        # NO_TRANSPORT
        snap = classify_feed_freshness(transport_ok=False, has_producer_signal=True)
        reached.add(snap.freshness_class)

        # CONFIG_ERROR
        snap = classify_feed_freshness(transport_ok=True, has_producer_signal=True, config_ok=False)
        reached.add(snap.freshness_class)

        assert reached == {c for c in FreshnessClass}
