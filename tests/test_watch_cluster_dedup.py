"""Increment E — SignalWatch cluster dedup (material-only, flag-guarded).

Increment B already suppresses *byte-identical* watch re-emits, but a watch whose
price/timestamp/density ticks every interval slips through (this is why one GBPCHF
cluster produced 28 near-identical SignalWatchJSON). Increment E collapses repeats
by their MATERIAL identity only — symbol, cluster/source, setup, direction, HTF
context, market-structure status, memory phase, M15 confirmation, and execution
status — ignoring the noisy numeric fields.

Flag ``SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED`` (default OFF). Suppresses only the
duplicate EMIT; the first watch and any material change always pass, decision
updates / final signals are never touched, and finalizer lifecycle tracking is
unaffected (the first watch already established the pending decision).
"""
from __future__ import annotations

from typing import Any

from analysis.signal_json_emitter import SignalJsonEmitter, SignalJsonEvent, build_signal_json_event

_FLAG = "SIGNAL_WATCH_CLUSTER_DEDUP_ENABLED"


def _fresh_emitter() -> SignalJsonEmitter:
    return SignalJsonEmitter(
        enabled=True,
        emit_watch=True,
        watch_transition_only=False,
        require_market_context=False,
        strict_lifecycle=False,
        dedup_ttl_seconds=300,
    )


def _reset_non_e(em: SignalJsonEmitter) -> None:
    """Defeat every dedup layer EXCEPT Increment E so only cluster-dedup can suppress."""
    em._emitted.clear()
    em._cluster_state.clear()
    em._cluster_watch_revisions.clear()
    em._cluster_watch_wall_seconds.clear()
    em._cluster_watch_event_seconds.clear()
    em._last_watch_content.clear()
    em._emitted_watch_refs.clear()


def _watch_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "symbol": "GBPCHF",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "resolved_family": "MICROBOOST_COUNTER_ENTRY",
        "status": "EARLY_SELL_WATCH",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "watch_direction": "SELL",
        "final_direction": "WAIT",
        "price_position": "MAIN_RESISTANCE",
        "reason": "buy_microboost_at_main_resistance_requires_rejection_or_breakout_confirmation",
        "cluster_id": "GBPCHF_20260610T050000Z",
        "signal_valid_time_utc": "2026-06-10T05:00:00+00:00",
        "signal_valid_price": 1.12348,
        "entry_reference_price": 1.12348,
        "entry_zone": [1.12348],
        "market_context_applied": True,
        "valid_for_execution": False,
    }
    payload.update(overrides)
    return payload


def _watch_event(**overrides: Any) -> SignalJsonEvent:
    event = build_signal_json_event(_watch_payload(**overrides))
    assert event is not None
    return event


# --------------------------------------------------------------------------- #
# Unit: _is_cluster_watch_duplicate — precise material-field guardrails
# --------------------------------------------------------------------------- #


def test_first_watch_is_never_a_duplicate():
    """Guardrail #5 — the first watch in a cluster always emits."""
    em = _fresh_emitter()
    assert em._is_cluster_watch_duplicate(_watch_payload()) is False


def test_identical_material_is_duplicate():
    em = _fresh_emitter()
    assert em._is_cluster_watch_duplicate(_watch_payload()) is False
    assert em._is_cluster_watch_duplicate(_watch_payload()) is True
    # price / timestamp noise does NOT break the dedup (the whole point of E vs B)
    assert em._is_cluster_watch_duplicate(_watch_payload(entry_reference_price=1.12399)) is True
    assert em._is_cluster_watch_duplicate(_watch_payload(signal_valid_time_utc="2026-06-10T05:02:00+00:00")) is True


def test_setup_change_is_not_duplicate():
    """Guardrail #6 — a setup transition re-emits."""
    em = _fresh_emitter()
    assert em._is_cluster_watch_duplicate(
        _watch_payload(tradeplan_preview={"setup_type": "SELL_REJECTION_WATCH"})
    ) is False
    assert em._is_cluster_watch_duplicate(
        _watch_payload(tradeplan_preview={"setup_type": "SELL_BREAKDOWN_WATCH"})
    ) is False


def test_direction_change_is_not_duplicate():
    """Guardrail #7 — a candidate/watch direction change re-emits."""
    em = _fresh_emitter()
    assert em._is_cluster_watch_duplicate(_watch_payload(candidate_direction="SELL", watch_direction="SELL")) is False
    assert em._is_cluster_watch_duplicate(_watch_payload(candidate_direction="BUY", watch_direction="BUY")) is False


def test_price_position_change_is_not_duplicate():
    """Guardrail #8 — a price_position change re-emits."""
    em = _fresh_emitter()
    assert em._is_cluster_watch_duplicate(_watch_payload(price_position="MAIN_RESISTANCE")) is False
    assert em._is_cluster_watch_duplicate(_watch_payload(price_position="MID_RANGE")) is False


def test_execution_status_change_is_not_duplicate():
    """Guardrail #9 — an execution-state change re-emits."""
    em = _fresh_emitter()
    assert em._is_cluster_watch_duplicate(_watch_payload(execution_status="WAIT_STRUCTURE_TARGET")) is False
    assert em._is_cluster_watch_duplicate(_watch_payload(execution_status="WAIT_M15_CONFIRMATION")) is False


def test_different_clusters_do_not_cross_suppress():
    """Guardrail #9 (owner test) — different symbols/clusters never suppress each other."""
    em = _fresh_emitter()
    assert em._is_cluster_watch_duplicate(_watch_payload(symbol="GBPCHF", cluster_id="A")) is False
    assert em._is_cluster_watch_duplicate(_watch_payload(symbol="USDCHF", cluster_id="B")) is False
    assert em._is_cluster_watch_duplicate(_watch_payload(symbol="GBPCHF", cluster_id="A")) is True


def test_ttl_lapse_allows_reemit():
    """Owner test #10 — once the dedup window lapses, a fresh watch is allowed again."""
    em = _fresh_emitter()
    assert em._is_cluster_watch_duplicate(_watch_payload()) is False
    assert em._is_cluster_watch_duplicate(_watch_payload()) is True
    # backdate the stored timestamp beyond the TTL window
    for key in list(em._cluster_semantic_watch):
        em._cluster_semantic_watch[key] -= em.dedup_ttl_seconds + 1
    assert em._is_cluster_watch_duplicate(_watch_payload()) is False


# --------------------------------------------------------------------------- #
# Integration through emit() — flag gating + decision-update exemption
# --------------------------------------------------------------------------- #


def test_flag_off_allows_reemit(monkeypatch):
    """Owner test #1 — flag OFF is a no-op; identical watch re-emits."""
    monkeypatch.setenv(_FLAG, "false")
    em = _fresh_emitter()
    assert em.emit(_watch_event()) is True
    _reset_non_e(em)
    assert em.emit(_watch_event()) is True


def test_flag_on_suppresses_duplicate(monkeypatch):
    """Owner tests #2/#7 — first watch emits, identical duplicate is suppressed."""
    monkeypatch.setenv(_FLAG, "true")
    em = _fresh_emitter()
    assert em.emit(_watch_event()) is True
    _reset_non_e(em)
    assert em.emit(_watch_event(entry_reference_price=1.12361)) is False


def test_flag_on_status_change_reemits(monkeypatch):
    """Owner test #3 — a setup/target change is material and re-emits."""
    monkeypatch.setenv(_FLAG, "true")
    em = _fresh_emitter()
    assert em.emit(_watch_event(tradeplan_preview={"setup_type": "SELL_REJECTION_WATCH"})) is True
    _reset_non_e(em)
    assert em.emit(_watch_event(tradeplan_preview={"setup_type": "SELL_BREAKDOWN_WATCH"})) is True


def test_decision_update_not_touched_by_cluster_dedup(monkeypatch):
    """Owner tests #2/#6 (guardrails) — a SignalDecisionUpdateJSON status never enters
    the watch cluster-dedup store and is never suppressed by it."""
    monkeypatch.setenv(_FLAG, "true")
    em = _fresh_emitter()
    em.emit(_watch_event())  # a watch DOES get recorded
    before = dict(em._cluster_semantic_watch)
    decision = build_signal_json_event(
        _watch_payload(status="NO_TRADE_REASONED", signal_family="SIGNAL_DECISION_UPDATE")
    )
    assert decision is not None
    em.emit(decision)
    # the decision-update did not add a cluster-dedup entry (E only governs watches)
    assert em._cluster_semantic_watch == before
