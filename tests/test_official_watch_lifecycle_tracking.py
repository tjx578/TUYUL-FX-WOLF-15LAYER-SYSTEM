"""Regression tests for official watch/continuation lifecycle tracking.

Closes the gap where an OFFICIAL watch/continuation candidate could be emitted as
``SignalWatchJSON`` without ever earning a terminal outcome (no DecisionUpdate, no
SignalJSON, no expiry). The fix tracks only OFFICIAL, actionable candidates and
deliberately keeps shadow/observability/telemetry pings out of the finalizer.

Boundary preserved (do not regress):
- ``tests/test_signal_block_finalizer.py::test_generic_microboost_watch_is_not_tracked_for_finalization``
  a watch WITHOUT lifecycle identity is still rejected by ``finalizer.track()``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from analysis.signal_block_finalizer import SignalBlockFinalizer
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

_should_track = WolfConstitutionalPipeline._should_track_lifecycle_candidate


def _official_watch(**overrides):
    payload = {
        "symbol": "CADJPY",
        "cluster_id": "CADJPY_20260608T033000Z",
        "status": "MICROBOOST_WATCH",
        "signal_family": "MICROBOOST_WATCH",
        "candidate_direction": "BUY",
        "watch_direction": "BUY",
        "validated_direction": None,
        "final_direction": "WAIT",
        "action": "WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION",
        "signal_valid_time_utc": "2026-06-08T03:32:29+00:00",
        "signal_valid_price": 115.5235,
        "entry_reference_price": 115.5235,
        "entry_zone": [115.5, 115.5235],
        "signal_quality": "WATCH_ONLY",
        "market_context_applied": True,
        "valid_for_execution": False,
        "pending_decision_id": "CADJPY_CADJPY_20260608T033000Z_M15_DECISION",
        "requires_m15_close": True,
    }
    payload.update(overrides)
    return payload


def _report():
    return {
        "symbol_activity": {
            "CADJPY": {
                "latest_event_utc": "2026-06-08T03:33:00+00:00",
                "latest_block_end_utc": "2026-06-08T03:33:00+00:00",
            }
        }
    }


# --------------------------------------------------------------------------- #
# Helper predicate: _should_track_lifecycle_candidate
# --------------------------------------------------------------------------- #


def test_should_track_accepts_official_watch():
    assert _should_track(_official_watch()) is True


def test_should_track_rejects_shadow_only():
    assert _should_track(_official_watch(shadow_only=True)) is False


def test_should_track_rejects_telemetry_only():
    assert _should_track(_official_watch(signal_quality="TELEMETRY_ONLY")) is False
    assert _should_track(_official_watch(signal_quality="DEBUG_ONLY")) is False


def test_should_track_rejects_missing_lifecycle_identity():
    payload = _official_watch()
    payload.pop("pending_decision_id")
    payload.pop("signal_id", None)
    assert _should_track(payload) is False


def test_should_track_rejects_non_lifecycle_status():
    # Pure continuation WAIT state is not a `_WATCH`/`_VALID` candidate, so it is
    # intentionally not auto-tracked by the helper.
    assert _should_track(_official_watch(status="WAIT_M15_CLOSE_OR_STRUCTURE_TARGET")) is False


def test_should_track_accepts_valid_status_variants():
    assert _should_track(_official_watch(status="SELL_TIMING_VALID")) is True
    assert _should_track(_official_watch(status="SELL_TIMING_VALID_BY_DIRECT_ABSORPTION")) is True


# --------------------------------------------------------------------------- #
# Finalizer adoption + guaranteed terminal outcome (no silent hang)
# --------------------------------------------------------------------------- #


def test_official_watch_is_adopted_and_emits_decision_update():
    """OFFICIAL watch with lifecycle identity is adopted and produces a terminal
    DecisionUpdate instead of hanging silently."""
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75)
    finalizer.track(_official_watch())

    assert finalizer.pending_symbols() == ["CADJPY"]

    outputs = finalizer.finalize(
        report=_report(),
        market_contexts={},  # no fresh context -> emits PENDING_MARKET_CONTEXT update
        now=datetime(2026, 6, 8, 3, 40, 0, tzinfo=UTC),
    )

    assert len(outputs) == 1
    assert outputs[0]["event"] == "signal_decision_update_json"
    assert outputs[0]["confirmation_policy"] == "PENDING_MARKET_CONTEXT"


def test_unidentified_watch_is_not_adopted_by_finalizer():
    """A watch WITHOUT lifecycle identity (shadow/observability) must NOT be adopted
    -- preserving the deliberate observability-vs-actionable boundary."""
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75)
    payload = _official_watch()
    payload.pop("pending_decision_id")
    payload.pop("requires_m15_close")

    finalizer.track(payload)

    assert finalizer.pending_symbols() == []
    assert (
        finalizer.finalize(
            report=_report(),
            market_contexts={},
            now=datetime(2026, 6, 8, 3, 40, 0, tzinfo=UTC),
        )
        == []
    )
