"""Tests for contracts.decision_bundle_builder — P1-B shadow bundle."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contracts.decision_bundle import DecisionBundle
from contracts.decision_bundle_builder import (
    build_shadow_decision_bundle,
    try_build_shadow_bundle,
)
from contracts.runtime_projection import EnvelopeCollection, dual_emit

SIGNAL_ID = "sig_p1b_shadow_bundle"
SYMBOL = "EURUSD"
TIMEFRAME = "H1"
RUNTIME_CTX = "stream:runtime:EURUSD:seq:42"


def _legacy(
    layer: str,
    status: str = "PASS",
    blockers: list[str] | None = None,
) -> dict:
    return {
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


def _fill_all_planes(coll: EnvelopeCollection) -> None:
    """Emit envelopes covering every plane used by DecisionBundle."""
    dual_emit(_legacy("L1"), coll)  # context
    dual_emit(_legacy("L2"), coll)  # alpha
    dual_emit(_legacy("L3"), coll)  # alpha
    dual_emit(_legacy("L5"), coll)  # validation
    dual_emit(_legacy("L6"), coll)  # risk
    dual_emit(_legacy("L7"), coll)  # validation
    dual_emit(_legacy("L9"), coll)  # alpha
    dual_emit(_legacy("L10"), coll)  # portfolio
    dual_emit(_legacy("L11"), coll)  # economics
    dual_emit(_legacy("L13"), coll)  # meta
    dual_emit(_legacy("V11"), coll)  # post_authority_veto — should be excluded


# ─────────────────────────────────────────────────────────────────────────
# Empty + basic build
# ─────────────────────────────────────────────────────────────────────────


class TestEmptyBundle:
    def test_empty_collection_builds_valid_bundle(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert isinstance(bundle, DecisionBundle)
        assert bundle.signal_id == SIGNAL_ID
        assert bundle.symbol == SYMBOL
        assert bundle.timeframe == TIMEFRAME
        assert bundle.runtime_context_ref == RUNTIME_CTX
        assert bundle.all_envelopes() == []
        assert bundle.hard_blockers() == []
        assert bundle.has_hard_failure() is False

    def test_explicit_created_at_is_preserved(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        fixed = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        bundle = build_shadow_decision_bundle(
            coll,
            timeframe=TIMEFRAME,
            runtime_context_ref=RUNTIME_CTX,
            created_at=fixed,
        )
        assert bundle.created_at == fixed


# ─────────────────────────────────────────────────────────────────────────
# Plane routing — every constitutional layer lands in the right bucket
# ─────────────────────────────────────────────────────────────────────────


class TestPlaneRouting:
    def test_l1_lands_in_context_evidence(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L1"), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert len(bundle.context_evidence) == 1
        assert bundle.context_evidence[0].layer_id == "L1"

    def test_alpha_layers_land_in_alpha_evidence(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        for lid in ("L2", "L3", "L4", "L9"):
            dual_emit(_legacy(lid), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert {e.layer_id for e in bundle.alpha_evidence} == {"L2", "L3", "L4", "L9"}

    def test_validation_layers_land_in_validation_evidence(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        for lid in ("L5", "L7", "L8"):
            dual_emit(_legacy(lid), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert {e.layer_id for e in bundle.validation_evidence} == {"L5", "L7", "L8"}

    def test_l6_lands_in_risk_evidence(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L6"), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert {e.layer_id for e in bundle.risk_evidence} == {"L6"}

    def test_l10_lands_in_portfolio_evidence(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L10"), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert {e.layer_id for e in bundle.portfolio_evidence} == {"L10"}

    def test_l11_lands_in_economics_evidence(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L11"), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert {e.layer_id for e in bundle.economics_evidence} == {"L11"}

    def test_meta_layers_land_in_meta_evidence(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L13"), coll)
        dual_emit(_legacy("L15"), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert {e.layer_id for e in bundle.meta_evidence} == {"L13", "L15"}


# ─────────────────────────────────────────────────────────────────────────
# V11 exclusion — hardest invariant
# ─────────────────────────────────────────────────────────────────────────


class TestV11Exclusion:
    def test_v11_never_enters_bundle(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        _fill_all_planes(coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        for env in bundle.all_envelopes():
            assert env.plane != "post_authority_veto"
            assert env.layer_id != "V11"

    def test_v11_remains_in_collection_for_audit(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("V11"), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        # Bundle is empty of V11 ...
        assert bundle.all_envelopes() == []
        # ... but the collection retains it for audit.
        assert "V11" in coll


# ─────────────────────────────────────────────────────────────────────────
# Hard-blocker semantics
# ─────────────────────────────────────────────────────────────────────────


class TestHardBlockers:
    def test_blocker_from_alpha_surfaces(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L2", status="FAIL", blockers=["MTA_VIOLATED"]), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert "MTA_VIOLATED" in bundle.hard_blockers()
        assert bundle.has_hard_failure() is True

    def test_blocker_from_risk_surfaces(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L6", status="FAIL", blockers=["RISK_CEILING"]), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert bundle.hard_blockers() == ["RISK_CEILING"]

    def test_blocker_from_economics_surfaces(self):
        # L11 economics is a real authority plane; its hard fails must hard-block.
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L11", status="FAIL", blockers=["RR_INSUFFICIENT"]), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert "RR_INSUFFICIENT" in bundle.hard_blockers()

    def test_meta_blocker_is_advisory_not_hard(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L13", status="FAIL", blockers=["GOVERNANCE_WARN"]), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert bundle.hard_blockers() == []
        assert bundle.has_hard_failure() is False

    def test_duplicate_blockers_dedup_across_planes(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L2", status="FAIL", blockers=["FRESHNESS_FAIL"]), coll)
        dual_emit(_legacy("L3", status="FAIL", blockers=["FRESHNESS_FAIL"]), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert bundle.hard_blockers() == ["FRESHNESS_FAIL"]


# ─────────────────────────────────────────────────────────────────────────
# Immutability / summary stability
# ─────────────────────────────────────────────────────────────────────────


class TestImmutabilityAndSummary:
    def test_bundle_is_frozen(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L1"), coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        from pydantic import ValidationError

        with pytest.raises((TypeError, AttributeError, ValidationError)):
            bundle.timeframe = "M15"  # type: ignore[misc]

    def test_summary_counts_include_economics(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        _fill_all_planes(coll)
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        summary = bundle.summary()
        counts = summary["counts"]
        assert counts["context"] == 1  # L1
        assert counts["alpha"] == 3  # L2, L3, L9
        assert counts["validation"] == 2  # L5, L7
        assert counts["risk"] == 1  # L6
        assert counts["portfolio"] == 1  # L10
        assert counts["economics"] == 1  # L11
        assert counts["meta"] == 1  # L13
        # V11 must NOT appear anywhere in counts.
        assert "post_authority_veto" not in counts

    def test_summary_is_deterministic_for_fixed_inputs(self):
        """Bundle summary is stable for the same envelopes + fixed created_at."""
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        _fill_all_planes(coll)
        fixed = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
        bundle_a = build_shadow_decision_bundle(
            coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX, created_at=fixed
        )
        bundle_b = build_shadow_decision_bundle(
            coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX, created_at=fixed
        )
        assert bundle_a.summary() == bundle_b.summary()


# ─────────────────────────────────────────────────────────────────────────
# No authority drift
# ─────────────────────────────────────────────────────────────────────────


class TestNoAuthorityDrift:
    def test_builder_does_not_invent_verdict_or_direction(self):
        """Builder is a pure projection; it cannot set direction=BUY/SELL."""
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        # Even if an alpha layer reports an advisory direction, the bundle
        # just carries it — no verdict is synthesised.
        dual_emit(_legacy("L2"), coll, direction="BUY")
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert bundle.alpha_evidence[0].direction == "BUY"  # advisory, preserved
        # Nothing on the bundle elevates it to a verdict.
        assert not hasattr(bundle, "verdict")
        assert not hasattr(bundle, "direction")

    def test_bundle_contains_no_account_state_via_evidence(self):
        """Account-state rejection at the envelope layer also protects the bundle."""
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        leaky = _legacy("L6")
        leaky["features"]["balance"] = 10_000.0
        dual_emit(leaky, coll)  # fails at envelope validation — recorded as failure
        bundle = build_shadow_decision_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert bundle.risk_evidence == []  # leak was blocked upstream
        # And the failure is still visible on the collection for audit.
        assert len(coll.failures()) == 1


# ─────────────────────────────────────────────────────────────────────────
# try_build_shadow_bundle — safe wrapper
# ─────────────────────────────────────────────────────────────────────────


class TestTryBuildSafe:
    def test_success_returns_bundle_and_none_diag(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        dual_emit(_legacy("L1"), coll)
        bundle, diag = try_build_shadow_bundle(coll, timeframe=TIMEFRAME, runtime_context_ref=RUNTIME_CTX)
        assert isinstance(bundle, DecisionBundle)
        assert diag is None

    def test_failure_returns_none_and_diag(self):
        coll = EnvelopeCollection(SIGNAL_ID, SYMBOL)
        # timeframe has min_length=2; a single char triggers validation error.
        bundle, diag = try_build_shadow_bundle(coll, timeframe="X", runtime_context_ref=RUNTIME_CTX)
        assert bundle is None
        assert diag is not None
        assert diag["signal_id"] == SIGNAL_ID
        assert diag["error_type"]  # any pydantic ValidationError or similar
        assert diag["error_message"]
