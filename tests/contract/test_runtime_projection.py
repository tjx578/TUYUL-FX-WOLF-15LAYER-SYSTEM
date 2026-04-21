"""Tests for contracts.runtime_projection — P1-A dual-emit safety contract."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from contracts.layer_envelope import LayerEnvelope
from contracts.runtime_projection import (
    EnvelopeCollection,
    ProjectionFailure,
    dual_emit,
)

SIGNAL_ID = "sig_p1a_dualemit"
SYMBOL = "EURUSD"


def _legacy(layer: str, status: str = "PASS", blockers: list[str] | None = None, extras: dict | None = None) -> dict:
    payload = {
        "layer": layer,
        "layer_version": "1.0.0",
        "timestamp": "2026-04-21T12:00:00+00:00",
        "input_ref": f"{SYMBOL}_{layer}_run",
        "status": status,
        "continuation_allowed": status in ("PASS", "WARN"),
        "blocker_codes": blockers or [],
        "warning_codes": [],
        "fallback_class": "NO_FALLBACK",
        "freshness_state": "FRESH",
        "warmup_state": "READY",
        "coherence_band": "HIGH",
        "coherence_score": 0.8,
        "features": {"aligned": True},
        "routing": {"next_legal_targets": []},
        "audit": {"rule_hits": [], "notes": []},
    }
    if extras:
        payload.update(extras)
    return payload


# ─────────────────────────────────────────────────────────────────────────
# EnvelopeCollection basics
# ─────────────────────────────────────────────────────────────────────────


class TestEnvelopeCollection:
    def test_requires_signal_id_and_symbol(self):
        with pytest.raises(ValueError):
            EnvelopeCollection("", SYMBOL)
        with pytest.raises(ValueError):
            EnvelopeCollection(SIGNAL_ID, "")

    def test_identity_fields(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        assert coll.signal_id == SIGNAL_ID
        assert coll.symbol == SYMBOL
        assert coll.created_at is not None
        assert len(coll) == 0

    def test_add_rejects_foreign_signal_id(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        env = LayerEnvelope(
            signal_id="other_sig",
            symbol=SYMBOL,
            layer_id="L1",
            module="analysis.layers.L1_constitutional",
            plane="context",
            status="PASS",
        )
        with pytest.raises(ValueError, match="signal_id"):
            coll.add(env)

    def test_add_rejects_duplicate_layer(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        env = dual_emit(_legacy("L2"), coll)
        assert env is not None
        # Second emit for same layer must raise via direct add().
        env2 = LayerEnvelope(
            signal_id=SIGNAL_ID,
            symbol=SYMBOL,
            layer_id="L2",
            module="analysis.layers.L2_constitutional",
            plane="alpha",
            status="PASS",
        )
        with pytest.raises(ValueError, match="append-only"):
            coll.add(env2)

    def test_contains_and_get(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L1"), coll)
        assert "L1" in coll
        assert "L99" not in coll
        assert coll.get("L1") is not None
        assert coll.get("L99") is None

    def test_by_plane_filters_correctly(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L1"), coll)
        dual_emit(_legacy("L2"), coll)
        dual_emit(_legacy("L6"), coll)
        assert len(coll.by_plane("context")) == 1
        assert len(coll.by_plane("alpha")) == 1
        assert len(coll.by_plane("risk")) == 1
        assert coll.by_plane("meta") == []


# ─────────────────────────────────────────────────────────────────────────
# Dual-emit safety contract — projection failures must NOT raise
# ─────────────────────────────────────────────────────────────────────────


class TestDualEmitSafety:
    def test_successful_projection_returns_envelope(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        env = dual_emit(_legacy("L2"), coll)
        assert isinstance(env, LayerEnvelope)
        assert "L2" in coll
        assert coll.failures() == []

    def test_account_state_leak_does_not_raise_into_legacy(self):
        """The whole point of dual-emit: a bad envelope must never break the pipeline."""
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        leaky = _legacy("L2")
        leaky["features"]["balance"] = 10_000.0  # forbidden
        result = dual_emit(leaky, coll)
        assert result is None
        assert len(coll.failures()) == 1
        assert coll.failures()[0].layer_id == "L2"
        assert "account state" in coll.failures()[0].error_message.lower()
        # Pipeline can continue: no envelope recorded for L2, no exception.
        assert "L2" not in coll

    def test_unknown_layer_id_captured_as_failure(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        payload = _legacy("L99")  # not in plane map
        result = dual_emit(payload, coll)
        assert result is None
        failures = coll.failures()
        assert len(failures) == 1
        assert failures[0].layer_id == "L99"
        assert failures[0].error_type == "KeyError"

    def test_missing_layer_field_captured(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        payload = _legacy("L2")
        payload.pop("layer")
        result = dual_emit(payload, coll)
        assert result is None
        assert coll.failures()[0].layer_id == "UNKNOWN"

    def test_duplicate_layer_second_call_fails_but_first_stays(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        first = dual_emit(_legacy("L1"), coll)
        second = dual_emit(_legacy("L1"), coll)
        assert first is not None
        assert second is None
        assert len(coll) == 1
        assert len(coll.failures()) == 1


# ─────────────────────────────────────────────────────────────────────────
# Hard-blocker aggregation mirrors DecisionBundle semantics
# ─────────────────────────────────────────────────────────────────────────


class TestHardBlockerAggregation:
    def test_hard_blockers_aggregate_from_non_meta_planes(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L2", status="FAIL", blockers=["MTA_VIOLATED"]), coll)
        dual_emit(_legacy("L6", status="FAIL", blockers=["RISK_CEILING"]), coll)
        blockers = coll.hard_blockers()
        assert "MTA_VIOLATED" in blockers
        assert "RISK_CEILING" in blockers

    def test_meta_blockers_are_advisory_not_hard(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L2"), coll)
        dual_emit(
            _legacy("L13", status="FAIL", blockers=["GOVERNANCE_WARN"]),
            coll,
        )
        # L13 is meta plane → advisory only.
        assert coll.hard_blockers() == []

    def test_post_authority_veto_is_not_pre_verdict_blocker(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L2"), coll)
        dual_emit(
            _legacy("V11", status="FAIL", blockers=["V11_SNIPER_FILTER"]),
            coll,
        )
        # V11 runs after L12; it is not a pre-L12 hard blocker.
        assert coll.hard_blockers() == []

    def test_degraded_without_blockers_is_not_hard_blocker(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L2", status="WARN"), coll)
        assert coll.hard_blockers() == []

    def test_hard_blockers_deduplicated(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L2", status="FAIL", blockers=["FRESHNESS_FAIL"]), coll)
        dual_emit(_legacy("L3", status="FAIL", blockers=["FRESHNESS_FAIL"]), coll)
        assert coll.hard_blockers() == ["FRESHNESS_FAIL"]


# ─────────────────────────────────────────────────────────────────────────
# Summary for journaling
# ─────────────────────────────────────────────────────────────────────────


class TestSummary:
    def test_summary_shape(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L1"), coll)
        dual_emit(_legacy("L2"), coll)
        dual_emit(_legacy("L6", status="FAIL", blockers=["RISK_CEILING"]), coll)
        summary = coll.summary()
        assert summary["signal_id"] == SIGNAL_ID
        assert summary["symbol"] == SYMBOL
        assert summary["envelope_count"] == 3
        assert summary["failure_count"] == 0
        assert summary["planes"]["context"] == 1
        assert summary["planes"]["alpha"] == 1
        assert summary["planes"]["risk"] == 1
        assert "RISK_CEILING" in summary["hard_blockers"]
        assert set(summary["layers"]) == {"L1", "L2", "L6"}

    def test_summary_counts_failures(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L1"), coll)
        bad = _legacy("L2")
        bad["features"]["equity"] = 1000.0
        dual_emit(bad, coll)
        summary = coll.summary()
        assert summary["envelope_count"] == 1
        assert summary["failure_count"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Thread-safety — parallel phase emit must not corrupt the store
# ─────────────────────────────────────────────────────────────────────────


class TestConcurrency:
    def test_parallel_emit_from_multiple_phases(self):
        """Enrichment engines 1-8 can emit in parallel; collection must stay consistent."""
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        # Use each of L1..L11 once so no duplicate-layer collisions occur.
        layers = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "L11"]
        barrier = threading.Barrier(len(layers))

        def emit(lid: str):
            barrier.wait()  # maximise contention
            return dual_emit(_legacy(lid), coll)

        with ThreadPoolExecutor(max_workers=len(layers)) as pool:
            results = list(pool.map(emit, layers))

        assert all(isinstance(r, LayerEnvelope) for r in results)
        assert len(coll) == len(layers)
        assert set(env.layer_id for env in coll.all_envelopes()) == set(layers)
        assert coll.failures() == []


# ─────────────────────────────────────────────────────────────────────────
# No authority drift — dual_emit cannot invent direction
# ─────────────────────────────────────────────────────────────────────────


class TestNoAuthorityDrift:
    def test_envelope_never_carries_buy_sell_without_explicit_caller(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        env = dual_emit(_legacy("L2"), coll)
        assert env is not None
        assert env.direction == "NONE"

    def test_caller_supplied_direction_passes_through(self):
        # Advisory direction from an alpha layer is allowed; only L12 decides.
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        env = dual_emit(_legacy("L3"), coll, direction="BUY")
        assert env is not None
        assert env.direction == "BUY"

    def test_projection_failure_record_is_frozen(self):
        failure = ProjectionFailure(layer_id="L2", error_type="ValueError", error_message="x")
        with pytest.raises(Exception):  # dataclass(frozen=True) → FrozenInstanceError
            failure.layer_id = "L3"  # type: ignore[misc]
