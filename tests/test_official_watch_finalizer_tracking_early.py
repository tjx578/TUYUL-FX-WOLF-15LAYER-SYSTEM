"""Increment D — Official Watch Finalizer Tracking (EARLY_* counter watches).

Increment C resolves a generic ``MICROBOOST_WATCH`` into an official directional
counter headline (EARLY_SELL_WATCH / EARLY_BUY_WATCH). But those watches come from
short absorption bursts that never form a clean SignalThrottle block, so the
existing pipeline gate ``_should_track_lifecycle_candidate`` rejects them on
``source_clean_block_ok`` -> they emit as SignalWatchJSON and then hang with no
terminal SignalDecisionUpdateJSON.

Increment D adds a flag-guarded admission path
(``SIGNAL_WATCH_FINALIZER_TRACK_EARLY_ENABLED``, default OFF) so a *resolved*
counter watch is adopted by the finalizer and earns a terminal decision. It is a
pure admission predicate — no execution behavior change.

Guardrails locked here:
- flag OFF -> EARLY_* not admitted (no behavior change)
- generic MICROBOOST_WATCH / shadow / telemetry / executable -> never admitted
- existing clean-block lifecycle tracking does not regress
- adoption never flips valid_for_execution / final_direction
"""

from __future__ import annotations

from datetime import UTC, datetime

from analysis.signal_block_finalizer import SignalBlockFinalizer
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

_FLAG = "SIGNAL_WATCH_FINALIZER_TRACK_EARLY_ENABLED"
_should_track_official = WolfConstitutionalPipeline._should_track_official_watch
_should_track_lifecycle = WolfConstitutionalPipeline._should_track_lifecycle_candidate


def _early_watch(**overrides):
    payload = {
        "symbol": "GBPCHF",
        "cluster_id": "GBPCHF_20260610T050000Z",
        "status": "EARLY_SELL_WATCH",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "resolved_family": "MICROBOOST_COUNTER_ENTRY",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "watch_direction": "SELL",
        "validated_direction": None,
        "final_direction": "WAIT",
        "action": "WAIT_REJECTION_OR_BREAKOUT_CONFIRMATION",
        "signal_valid_time_utc": "2026-06-10T05:00:00+00:00",
        "signal_valid_price": 1.12348,
        "entry_reference_price": 1.12348,
        "entry_zone": [1.12340, 1.12348],
        "signal_quality": "WATCH_ONLY",
        "market_context_applied": True,
        "valid_for_execution": False,
        # lifecycle identity (set by _mark_official_lifecycle_candidate in the real flow)
        "pending_decision_id": "GBPCHF_GBPCHF_20260610T050000Z_M15_DECISION",
        "requires_m15_close": True,
        # resolved counter watches come from no-clean-block bursts
        "source_clean_block_confirmed": False,
    }
    payload.update(overrides)
    return payload


def _report():
    return {
        "symbol_activity": {
            "GBPCHF": {
                "latest_event_utc": "2026-06-10T05:01:00+00:00",
                "latest_block_end_utc": "2026-06-10T05:01:00+00:00",
            }
        }
    }


# --------------------------------------------------------------------------- #
# Admission predicate: _should_track_official_watch (the owner's 7 cases)
# --------------------------------------------------------------------------- #


def test_flag_off_is_a_noop(monkeypatch):
    """Test 1 — flag OFF: EARLY_SELL_WATCH is not admitted (no behavior change)."""
    monkeypatch.delenv(_FLAG, raising=False)
    assert _should_track_official(_early_watch()) is False


def test_flag_on_early_sell_watch_admitted(monkeypatch):
    """Test 2 — flag ON: a resolved EARLY_SELL_WATCH is admitted for tracking."""
    monkeypatch.setenv(_FLAG, "true")
    assert _should_track_official(_early_watch()) is True


def test_flag_on_early_buy_watch_admitted(monkeypatch):
    """Test 3 — flag ON: inverse EARLY_BUY_WATCH is admitted for tracking."""
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_watch(
        status="EARLY_BUY_WATCH",
        raw_direction="SELL",
        candidate_direction="BUY",
        watch_direction="BUY",
    )
    assert _should_track_official(payload) is True


def test_flag_on_generic_microboost_watch_not_admitted(monkeypatch):
    """Test 4 — a generic (unresolved) MICROBOOST_WATCH is never admitted by this path."""
    monkeypatch.setenv(_FLAG, "true")
    generic = _early_watch(
        status="MICROBOOST_WATCH",
        signal_family="MICROBOOST_WATCH",
        resolved_family="WATCH_ONLY_PENDING_CONTEXT",
        raw_direction="BUY",
        candidate_direction="BUY",
        watch_direction="BUY",
    )
    assert _should_track_official(generic) is False


def test_flag_on_shadow_and_telemetry_not_admitted(monkeypatch):
    """Test 5 — shadow_only / telemetry_only pings are never admitted."""
    monkeypatch.setenv(_FLAG, "true")
    assert _should_track_official(_early_watch(shadow_only=True)) is False
    assert _should_track_official(_early_watch(signal_quality="TELEMETRY_ONLY")) is False
    assert _should_track_official(_early_watch(signal_quality="DEBUG_ONLY")) is False


def test_flag_on_executable_or_non_wait_not_admitted(monkeypatch):
    """Test 6 (admission half) — never admit something claiming execution / a non-WAIT final."""
    monkeypatch.setenv(_FLAG, "true")
    assert _should_track_official(_early_watch(valid_for_execution=True)) is False
    assert _should_track_official(_early_watch(is_final_signal=True)) is False
    assert _should_track_official(_early_watch(final_direction="SELL")) is False


def test_missing_lifecycle_identity_not_admitted(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_watch()
    payload.pop("pending_decision_id")
    payload.pop("signal_id", None)
    assert _should_track_official(payload) is False


def test_existing_clean_block_tracking_does_not_regress():
    """Test 7 — the existing clean-block lifecycle gate is untouched: a clean-block
    SELL_TIMING_WATCH is still tracked, and EARLY_* still falls outside it (so the new
    flag-guarded path is the *only* thing that admits no-clean-block counter watches).
    """
    clean_timing = _early_watch(
        status="SELL_TIMING_WATCH",
        source_clean_block_confirmed=True,
    )
    assert _should_track_lifecycle(clean_timing) is True
    # EARLY_* from a no-clean-block burst is NOT admitted by the legacy gate (any flag state)
    assert _should_track_lifecycle(_early_watch()) is False


# --------------------------------------------------------------------------- #
# Finalizer end-to-end: adopted EARLY watch earns a terminal DecisionUpdate
# --------------------------------------------------------------------------- #


def test_early_watch_reaches_finalizer_and_emits_decision_update():
    """Test 2/6 (lifecycle half) — an adopted EARLY_SELL_WATCH produces a terminal
    SignalDecisionUpdateJSON and is never flipped to executable."""
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75)
    payload = _early_watch()
    finalizer.track(payload)

    assert finalizer.pending_symbols() == ["GBPCHF"]

    outputs = finalizer.finalize(
        report=_report(),
        market_contexts={},  # no fresh context -> PENDING_MARKET_CONTEXT terminal update
        now=datetime(2026, 6, 10, 5, 10, 0, tzinfo=UTC),
    )

    assert len(outputs) == 1
    assert outputs[0]["event"] == "signal_decision_update_json"
    # guardrail: adoption never promotes execution
    assert payload["valid_for_execution"] is False
    assert payload["final_direction"] == "WAIT"


def test_early_watch_duplicate_cluster_collapses_to_one_pending():
    """Guardrail #5 — repeated watches from the same cluster dedupe to a single
    pending decision (keyed by pending_decision_id), so no DecisionUpdate spam."""
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75)
    finalizer.track(_early_watch())
    finalizer.track(_early_watch())
    finalizer.track(_early_watch())
    assert finalizer.pending_symbols() == ["GBPCHF"]
    outputs = finalizer.finalize(
        report=_report(),
        market_contexts={},
        now=datetime(2026, 6, 10, 5, 10, 0, tzinfo=UTC),
    )
    assert len(outputs) == 1
