"""Tests for L1, L2, L3 router evaluators and Phase 1 evaluator chain.

Validates:
- L1/L2/L3 evaluators individually (PASS/WARN/FAIL scenarios)
- Blocker detection for each layer
- Coherence band thresholds
- Upstream flag injection
- Phase 1 evaluator chain halt-on-failure semantics
- build_*_input_from_dict adapters
"""

from __future__ import annotations

import pytest

from constitution.l1_router_evaluator import (
    BlockerCode as L1Blocker,
)
from constitution.l1_router_evaluator import (
    CoherenceBand as L1Band,
)
from constitution.l1_router_evaluator import (
    FallbackClass as L1Fallback,
)
from constitution.l1_router_evaluator import (
    FreshnessState as L1Freshness,
)
from constitution.l1_router_evaluator import (
    L1Input,
    L1RouterEvaluator,
    L1Status,
    build_l1_input_from_dict,
    example_payloads,
)
from constitution.l1_router_evaluator import (
    WarmupState as L1Warmup,
)
from constitution.l2_router_evaluator import (
    BlockerCode as L2Blocker,
)
from constitution.l2_router_evaluator import (
    FallbackClass as L2Fallback,
)
from constitution.l2_router_evaluator import (
    FreshnessState as L2Freshness,
)
from constitution.l2_router_evaluator import (
    L2Input,
    L2RouterEvaluator,
    L2Status,
    build_l2_input_from_dict,
)
from constitution.l2_router_evaluator import (
    WarmupState as L2Warmup,
)
from constitution.l3_router_evaluator import (
    BlockerCode as L3Blocker,
)
from constitution.l3_router_evaluator import (
    FallbackClass as L3Fallback,
)
from constitution.l3_router_evaluator import (
    FreshnessState as L3Freshness,
)
from constitution.l3_router_evaluator import (
    L3Input,
    L3RouterEvaluator,
    L3Status,
    build_l3_input_from_dict,
)
from constitution.l3_router_evaluator import (
    WarmupState as L3Warmup,
)
from constitution.phase1_chain_adapter import (
    Phase1RouterEvaluatorAdapter,
    build_phase1_payloads_from_dict,
)

# ═══════════════════════════════════════════════════════════════
# §1  L1 ROUTER EVALUATOR
# ═══════════════════════════════════════════════════════════════


class TestL1RouterEvaluator:
    """L1 context governor evaluation tests."""

    def _clean_pass_input(self) -> L1Input:
        return L1Input(
            input_ref="TEST_001",
            timestamp="2026-04-01T10:00:00Z",
            context_sources_used=("regime_service", "session_state"),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.91,
            freshness_state=L1Freshness.FRESH,
            warmup_state=L1Warmup.READY,
        )

    def test_clean_pass(self):
        ev = L1RouterEvaluator()
        result = ev.evaluate(self._clean_pass_input())
        assert result.status == L1Status.PASS
        assert result.continuation_allowed is True
        assert result.blocker_codes == ()
        assert result.coherence_band == L1Band.HIGH
        assert result.routing["next_legal_targets"] == ["L2"]

    def test_mid_coherence_pass(self):
        ev = L1RouterEvaluator()
        inp = L1Input(
            input_ref="TEST_002",
            timestamp="2026-04-01T10:00:00Z",
            context_sources_used=("regime_service",),
            market_regime="RANGING",
            dominant_force="MIXED",
            coherence_score=0.70,
            freshness_state=L1Freshness.FRESH,
            warmup_state=L1Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.status == L1Status.PASS
        assert result.coherence_band == L1Band.MID

    def test_degraded_legal_warn(self):
        ev = L1RouterEvaluator()
        inp = L1Input(
            input_ref="TEST_003",
            timestamp="2026-04-01T10:01:00Z",
            context_sources_used=("preserved_snapshot",),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.74,
            freshness_state=L1Freshness.STALE_PRESERVED,
            warmup_state=L1Warmup.PARTIAL,
            fallback_class=L1Fallback.LEGAL_EMERGENCY_PRESERVE,
            fallback_used=True,
        )
        result = ev.evaluate(inp)
        assert result.status == L1Status.WARN
        assert result.continuation_allowed is True
        assert "STALE_PRESERVED_CONTEXT" in result.warning_codes
        assert "PARTIAL_WARMUP" in result.warning_codes
        assert "EMERGENCY_PRESERVE_FALLBACK" in result.warning_codes

    def test_low_coherence_fail(self):
        ev = L1RouterEvaluator()
        inp = L1Input(
            input_ref="TEST_004",
            timestamp="2026-04-01T10:02:00Z",
            context_sources_used=("regime_service",),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.50,
            freshness_state=L1Freshness.FRESH,
            warmup_state=L1Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.status == L1Status.FAIL
        assert result.continuation_allowed is False
        assert result.coherence_band == L1Band.LOW

    def test_no_producer_fail(self):
        ev = L1RouterEvaluator()
        inp = L1Input(
            input_ref="TEST_005",
            timestamp="2026-04-01T10:03:00Z",
            context_sources_used=(),
            market_regime="UNKNOWN",
            dominant_force="MIXED",
            coherence_score=0.95,
            freshness_state=L1Freshness.NO_PRODUCER,
            warmup_state=L1Warmup.INSUFFICIENT,
            required_producer_missing=True,
        )
        result = ev.evaluate(inp)
        assert result.status == L1Status.FAIL
        assert result.continuation_allowed is False
        assert L1Blocker.REQUIRED_PRODUCER_MISSING.value in result.blocker_codes
        assert L1Blocker.WARMUP_INSUFFICIENT.value in result.blocker_codes

    def test_illegal_fallback_fail(self):
        ev = L1RouterEvaluator()
        inp = L1Input(
            input_ref="TEST_006",
            timestamp="2026-04-01T10:04:00Z",
            context_sources_used=("regime_service",),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.90,
            freshness_state=L1Freshness.FRESH,
            warmup_state=L1Warmup.READY,
            fallback_class=L1Fallback.ILLEGAL_FALLBACK,
        )
        result = ev.evaluate(inp)
        assert result.status == L1Status.FAIL
        assert L1Blocker.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value in result.blocker_codes

    def test_contract_malformed_fail(self):
        ev = L1RouterEvaluator()
        inp = L1Input(
            input_ref="TEST_007",
            timestamp="2026-04-01T10:05:00Z",
            context_sources_used=("regime_service",),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.90,
            freshness_state=L1Freshness.FRESH,
            warmup_state=L1Warmup.READY,
            contract_payload_malformed=True,
        )
        result = ev.evaluate(inp)
        assert result.status == L1Status.FAIL
        assert L1Blocker.CONTRACT_PAYLOAD_MALFORMED.value in result.blocker_codes

    def test_to_dict_contains_required_keys(self):
        ev = L1RouterEvaluator()
        d = ev.evaluate(self._clean_pass_input()).to_dict()
        for key in ("layer", "layer_version", "status", "continuation_allowed",
                     "blocker_codes", "warning_codes", "coherence_band",
                     "coherence_score", "features", "routing", "audit"):
            assert key in d

    def test_build_from_dict(self):
        payload = {
            "input_ref": "EURUSD_H1_run_001",
            "timestamp": "2026-04-01T10:00:00Z",
            "context_sources_used": ["regime_service"],
            "market_regime": "TRENDING",
            "dominant_force": "MOMENTUM",
            "coherence_score": 0.88,
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        }
        inp = build_l1_input_from_dict(payload)
        assert inp.coherence_score == 0.88
        assert inp.freshness_state == L1Freshness.FRESH

    def test_build_from_dict_missing_field(self):
        with pytest.raises(ValueError, match="Missing required"):
            build_l1_input_from_dict({"input_ref": "X"})

    def test_example_payloads_all_evaluate(self):
        ev = L1RouterEvaluator()
        for inp in example_payloads():
            result = ev.evaluate(inp)
            assert result.status in (L1Status.PASS, L1Status.WARN, L1Status.FAIL)

    def test_threshold_boundary_high(self):
        ev = L1RouterEvaluator()
        inp = L1Input(
            input_ref="T_BOUNDARY",
            timestamp="2026-04-01T10:00:00Z",
            context_sources_used=("src",),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.85,
            freshness_state=L1Freshness.FRESH,
            warmup_state=L1Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.coherence_band == L1Band.HIGH
        assert result.status == L1Status.PASS

    def test_threshold_boundary_mid(self):
        ev = L1RouterEvaluator()
        inp = L1Input(
            input_ref="T_BOUNDARY_MID",
            timestamp="2026-04-01T10:00:00Z",
            context_sources_used=("src",),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.649,
            freshness_state=L1Freshness.FRESH,
            warmup_state=L1Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.coherence_band == L1Band.LOW
        assert result.status == L1Status.FAIL


# ═══════════════════════════════════════════════════════════════
# §2  L2 ROUTER EVALUATOR
# ═══════════════════════════════════════════════════════════════


class TestL2RouterEvaluator:
    """L2 MTA structure legality tests."""

    def _clean_pass_input(self) -> L2Input:
        return L2Input(
            input_ref="TEST_L2_001",
            timestamp="2026-04-01T10:00:00Z",
            structure_sources_used=["mtf_alignment", "fusion_sync"],
            required_timeframes=["D1", "H4"],
            coverage_target_timeframes=["D1", "H4"],
            available_timeframes=["D1", "H4"],
            alignment_score=0.89,
            hierarchy_followed=True,
            aligned=True,
            upstream_l1_continuation_allowed=True,
            freshness_state=L2Freshness.FRESH,
            warmup_state=L2Warmup.READY,
        )

    def test_clean_pass(self):
        ev = L2RouterEvaluator()
        result = ev.evaluate(self._clean_pass_input())
        assert result.status == L2Status.PASS
        assert result.continuation_allowed is True
        assert result.blocker_codes == []

    def test_degraded_warn(self):
        ev = L2RouterEvaluator()
        inp = L2Input(
            input_ref="TEST_L2_002",
            timestamp="2026-04-01T10:01:00Z",
            structure_sources_used=["mtf_alignment"],
            required_timeframes=["D1", "H4"],
            coverage_target_timeframes=["D1", "H4", "H1"],
            available_timeframes=["D1", "H4"],
            alignment_score=0.77,
            hierarchy_followed=True,
            aligned=False,
            upstream_l1_continuation_allowed=True,
            freshness_state=L2Freshness.STALE_PRESERVED,
            warmup_state=L2Warmup.PARTIAL,
            fallback_class=L2Fallback.LEGAL_EMERGENCY_PRESERVE,
            fallback_used=True,
        )
        result = ev.evaluate(inp)
        assert result.status == L2Status.WARN
        assert result.continuation_allowed is True
        assert "STRUCTURE_NOT_FULLY_ALIGNED" in result.warning_codes
        assert "STALE_PRESERVED_STRUCTURE" in result.warning_codes

    def test_upstream_l1_blocked(self):
        ev = L2RouterEvaluator()
        inp = L2Input(
            input_ref="TEST_L2_003",
            timestamp="2026-04-01T10:02:00Z",
            structure_sources_used=[],
            required_timeframes=["D1", "H4"],
            coverage_target_timeframes=["D1", "H4"],
            available_timeframes=["H4"],
            alignment_score=0.40,
            hierarchy_followed=False,
            aligned=False,
            upstream_l1_continuation_allowed=False,
            freshness_state=L2Freshness.NO_PRODUCER,
            warmup_state=L2Warmup.INSUFFICIENT,
        )
        result = ev.evaluate(inp)
        assert result.status == L2Status.FAIL
        assert result.continuation_allowed is False
        assert L2Blocker.UPSTREAM_L1_NOT_CONTINUABLE.value in result.blocker_codes

    def test_hierarchy_violated(self):
        ev = L2RouterEvaluator()
        inp = L2Input(
            input_ref="TEST_L2_HIER",
            timestamp="2026-04-01T10:03:00Z",
            structure_sources_used=["mtf_alignment"],
            required_timeframes=["D1", "H4"],
            coverage_target_timeframes=["D1", "H4"],
            available_timeframes=["D1", "H4"],
            alignment_score=0.88,
            hierarchy_followed=False,
            aligned=True,
            upstream_l1_continuation_allowed=True,
            freshness_state=L2Freshness.FRESH,
            warmup_state=L2Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.status == L2Status.FAIL
        assert L2Blocker.MTA_HIERARCHY_VIOLATED.value in result.blocker_codes

    def test_low_alignment_fail(self):
        ev = L2RouterEvaluator()
        inp = L2Input(
            input_ref="TEST_L2_LOW",
            timestamp="2026-04-01T10:04:00Z",
            structure_sources_used=["mtf_alignment"],
            required_timeframes=["D1", "H4"],
            coverage_target_timeframes=["D1", "H4"],
            available_timeframes=["D1", "H4"],
            alignment_score=0.50,
            hierarchy_followed=True,
            aligned=False,
            upstream_l1_continuation_allowed=True,
            freshness_state=L2Freshness.FRESH,
            warmup_state=L2Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.status == L2Status.FAIL
        assert result.coherence_band == "LOW"

    def test_build_from_dict(self):
        payload = {
            "input_ref": "EURUSD_H1",
            "timestamp": "2026-04-01T10:00:00Z",
            "structure_sources_used": ["mtf"],
            "required_timeframes": ["D1", "H4"],
            "coverage_target_timeframes": ["D1", "H4"],
            "available_timeframes": ["D1", "H4"],
            "alignment_score": 0.88,
            "hierarchy_followed": True,
            "aligned": True,
            "upstream_l1_continuation_allowed": True,
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        }
        inp = build_l2_input_from_dict(payload)
        assert inp.alignment_score == 0.88

    def test_build_from_dict_missing_field(self):
        with pytest.raises(ValueError, match="Missing required"):
            build_l2_input_from_dict({"input_ref": "X"})

    def test_to_dict(self):
        ev = L2RouterEvaluator()
        d = ev.evaluate(self._clean_pass_input()).to_dict()
        assert d["layer"] == "L2"
        assert d["status"] == "PASS"
        assert "features" in d


# ═══════════════════════════════════════════════════════════════
# §3  L3 ROUTER EVALUATOR
# ═══════════════════════════════════════════════════════════════


class TestL3RouterEvaluator:
    """L3 trend confirmation legality tests."""

    def _clean_pass_input(self) -> L3Input:
        return L3Input(
            input_ref="TEST_L3_001",
            timestamp="2026-04-01T10:00:00Z",
            trend_sources_used=["ema_stack", "momentum_sync"],
            required_trend_sources=["ema_stack", "momentum_sync"],
            available_trend_sources=["ema_stack", "momentum_sync"],
            confirmation_score=0.90,
            trend_confirmed=True,
            structure_conflict=False,
            upstream_l2_continuation_allowed=True,
            freshness_state=L3Freshness.FRESH,
            warmup_state=L3Warmup.READY,
        )

    def test_clean_pass(self):
        ev = L3RouterEvaluator()
        result = ev.evaluate(self._clean_pass_input())
        assert result.status == L3Status.PASS
        assert result.continuation_allowed is True
        assert result.blocker_codes == []

    def test_degraded_warn(self):
        ev = L3RouterEvaluator()
        inp = L3Input(
            input_ref="TEST_L3_002",
            timestamp="2026-04-01T10:01:00Z",
            trend_sources_used=["ema_stack", "preserved_snapshot"],
            required_trend_sources=["ema_stack", "momentum_sync"],
            available_trend_sources=["ema_stack", "momentum_sync"],
            confirmation_score=0.74,
            trend_confirmed=True,
            structure_conflict=False,
            upstream_l2_continuation_allowed=True,
            freshness_state=L3Freshness.STALE_PRESERVED,
            warmup_state=L3Warmup.PARTIAL,
            fallback_class=L3Fallback.LEGAL_EMERGENCY_PRESERVE,
            fallback_used=True,
        )
        result = ev.evaluate(inp)
        assert result.status == L3Status.WARN
        assert result.continuation_allowed is True
        assert "STALE_PRESERVED_TREND_CONTEXT" in result.warning_codes
        assert "PARTIAL_WARMUP" in result.warning_codes

    def test_trend_not_confirmed_fail(self):
        ev = L3RouterEvaluator()
        inp = L3Input(
            input_ref="TEST_L3_003",
            timestamp="2026-04-01T10:02:00Z",
            trend_sources_used=[],
            required_trend_sources=["ema_stack"],
            available_trend_sources=["ema_stack"],
            confirmation_score=0.52,
            trend_confirmed=False,
            structure_conflict=True,
            upstream_l2_continuation_allowed=True,
            freshness_state=L3Freshness.FRESH,
            warmup_state=L3Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.status == L3Status.FAIL
        assert L3Blocker.TREND_CONFIRMATION_UNAVAILABLE.value in result.blocker_codes

    def test_structure_conflict_fail(self):
        ev = L3RouterEvaluator()
        inp = L3Input(
            input_ref="TEST_L3_SC",
            timestamp="2026-04-01T10:03:00Z",
            trend_sources_used=["ema_stack"],
            required_trend_sources=["ema_stack"],
            available_trend_sources=["ema_stack"],
            confirmation_score=0.88,
            trend_confirmed=True,
            structure_conflict=True,
            upstream_l2_continuation_allowed=True,
            freshness_state=L3Freshness.FRESH,
            warmup_state=L3Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.status == L3Status.FAIL
        assert L3Blocker.TREND_STRUCTURE_CONFLICT.value in result.blocker_codes

    def test_upstream_l2_blocked(self):
        ev = L3RouterEvaluator()
        inp = L3Input(
            input_ref="TEST_L3_UPS",
            timestamp="2026-04-01T10:04:00Z",
            trend_sources_used=["ema_stack"],
            required_trend_sources=["ema_stack"],
            available_trend_sources=["ema_stack"],
            confirmation_score=0.90,
            trend_confirmed=True,
            structure_conflict=False,
            upstream_l2_continuation_allowed=False,
            freshness_state=L3Freshness.FRESH,
            warmup_state=L3Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.status == L3Status.FAIL
        assert L3Blocker.UPSTREAM_L2_NOT_CONTINUABLE.value in result.blocker_codes

    def test_low_confirmation_fail(self):
        ev = L3RouterEvaluator()
        inp = L3Input(
            input_ref="TEST_L3_LOW",
            timestamp="2026-04-01T10:05:00Z",
            trend_sources_used=["ema_stack"],
            required_trend_sources=["ema_stack"],
            available_trend_sources=["ema_stack"],
            confirmation_score=0.50,
            trend_confirmed=True,
            structure_conflict=False,
            upstream_l2_continuation_allowed=True,
            freshness_state=L3Freshness.FRESH,
            warmup_state=L3Warmup.READY,
        )
        result = ev.evaluate(inp)
        assert result.status == L3Status.FAIL
        assert result.coherence_band == "LOW"

    def test_build_from_dict(self):
        payload = {
            "input_ref": "EURUSD_H1",
            "timestamp": "2026-04-01T10:00:00Z",
            "trend_sources_used": ["ema_stack"],
            "required_trend_sources": ["ema_stack"],
            "available_trend_sources": ["ema_stack"],
            "confirmation_score": 0.88,
            "trend_confirmed": True,
            "structure_conflict": False,
            "upstream_l2_continuation_allowed": True,
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        }
        inp = build_l3_input_from_dict(payload)
        assert inp.confirmation_score == 0.88

    def test_build_from_dict_missing_field(self):
        with pytest.raises(ValueError, match="Missing required"):
            build_l3_input_from_dict({"input_ref": "X"})

    def test_to_dict(self):
        ev = L3RouterEvaluator()
        d = ev.evaluate(self._clean_pass_input()).to_dict()
        assert d["layer"] == "L3"
        assert d["status"] == "PASS"


# ═══════════════════════════════════════════════════════════════
# §4  PHASE 1 ROUTER EVALUATOR CHAIN
# ═══════════════════════════════════════════════════════════════

# ── Canonical test payloads ───────────────────────────────────

_TS = "2026-04-01T10:00:00Z"
_REF = "EURUSD_H1_run_001"


def _l1_pass_payload() -> dict:
    return {
        "input_ref": _REF,
        "timestamp": _TS,
        "context_sources_used": ["regime_service", "session_state"],
        "market_regime": "TRENDING",
        "dominant_force": "MOMENTUM",
        "coherence_score": 0.91,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


def _l1_fail_payload() -> dict:
    return {
        "input_ref": _REF,
        "timestamp": _TS,
        "context_sources_used": [],
        "market_regime": "UNKNOWN",
        "dominant_force": "MIXED",
        "coherence_score": 0.95,
        "freshness_state": "NO_PRODUCER",
        "warmup_state": "INSUFFICIENT",
        "required_producer_missing": True,
    }


def _l2_pass_payload() -> dict:
    return {
        "input_ref": _REF,
        "timestamp": _TS,
        "structure_sources_used": ["mtf_alignment"],
        "required_timeframes": ["D1", "H4"],
        "coverage_target_timeframes": ["D1", "H4"],
        "available_timeframes": ["D1", "H4"],
        "alignment_score": 0.89,
        "hierarchy_followed": True,
        "aligned": True,
        "upstream_l1_continuation_allowed": True,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


def _l2_fail_payload() -> dict:
    return {
        "input_ref": _REF,
        "timestamp": _TS,
        "structure_sources_used": [],
        "required_timeframes": ["D1", "H4"],
        "coverage_target_timeframes": ["D1", "H4"],
        "available_timeframes": ["H4"],
        "alignment_score": 0.40,
        "hierarchy_followed": False,
        "aligned": False,
        "upstream_l1_continuation_allowed": True,
        "freshness_state": "NO_PRODUCER",
        "warmup_state": "INSUFFICIENT",
    }


def _l3_pass_payload() -> dict:
    return {
        "input_ref": _REF,
        "timestamp": _TS,
        "trend_sources_used": ["ema_stack", "momentum_sync"],
        "required_trend_sources": ["ema_stack"],
        "available_trend_sources": ["ema_stack"],
        "confirmation_score": 0.88,
        "trend_confirmed": True,
        "structure_conflict": False,
        "upstream_l2_continuation_allowed": True,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


def _l3_fail_payload() -> dict:
    return {
        "input_ref": _REF,
        "timestamp": _TS,
        "trend_sources_used": [],
        "required_trend_sources": ["ema_stack"],
        "available_trend_sources": ["ema_stack"],
        "confirmation_score": 0.52,
        "trend_confirmed": False,
        "structure_conflict": True,
        "upstream_l2_continuation_allowed": True,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


class TestPhase1EvaluatorChainAllPass:
    def test_all_pass(self):
        adapter = Phase1RouterEvaluatorAdapter()
        result = adapter.run(_l1_pass_payload(), _l2_pass_payload(), _l3_pass_payload())
        assert result.halted is False
        assert result.halted_at is None
        assert result.continuation_allowed is True
        assert result.chain_status in ("PASS", "WARN")
        assert "L1" in result.summary_status
        assert "L2" in result.summary_status
        assert "L3" in result.summary_status
        assert result.phase == "PHASE_1_FOUNDATION"

    def test_all_pass_to_dict(self):
        adapter = Phase1RouterEvaluatorAdapter()
        result = adapter.run(_l1_pass_payload(), _l2_pass_payload(), _l3_pass_payload())
        d = result.to_dict()
        assert d["phase"] == "PHASE_1_FOUNDATION"
        assert d["continuation_allowed"] is True
        assert "L1" in d["layer_results"]
        assert "L2" in d["layer_results"]
        assert "L3" in d["layer_results"]


class TestPhase1EvaluatorChainHaltL1:
    def test_l1_fail_halts_chain(self):
        adapter = Phase1RouterEvaluatorAdapter()
        result = adapter.run(_l1_fail_payload(), _l2_pass_payload(), _l3_pass_payload())
        assert result.halted is True
        assert result.halted_at == "L1"
        assert result.continuation_allowed is False
        assert result.chain_status == "FAIL"
        assert "L1" in result.layer_results
        assert "L2" not in result.layer_results
        assert "L3" not in result.layer_results


class TestPhase1EvaluatorChainHaltL2:
    def test_l2_fail_halts_chain(self):
        adapter = Phase1RouterEvaluatorAdapter()
        result = adapter.run(_l1_pass_payload(), _l2_fail_payload(), _l3_pass_payload())
        assert result.halted is True
        assert result.halted_at == "L2"
        assert result.continuation_allowed is False
        assert "L1" in result.layer_results
        assert "L2" in result.layer_results
        assert "L3" not in result.layer_results


class TestPhase1EvaluatorChainHaltL3:
    def test_l3_fail_halts_chain(self):
        adapter = Phase1RouterEvaluatorAdapter()
        result = adapter.run(_l1_pass_payload(), _l2_pass_payload(), _l3_fail_payload())
        assert result.halted is True
        assert result.halted_at == "L3"
        assert result.continuation_allowed is False
        assert "L1" in result.layer_results
        assert "L2" in result.layer_results
        assert "L3" in result.layer_results


class TestPhase1EvaluatorChainUpstream:
    def test_upstream_injection_l1_to_l2(self):
        """L1 result's continuation_allowed is injected into L2 payload."""
        adapter = Phase1RouterEvaluatorAdapter()
        # L2 payload does NOT have upstream_l1_continuation_allowed set
        l2 = _l2_pass_payload()
        del l2["upstream_l1_continuation_allowed"]
        # But it gets injected from L1 result
        result = adapter.run(_l1_pass_payload(), l2, _l3_pass_payload())
        assert result.halted is False
        # Layer 2 got the upstream flag from L1
        l2r = result.layer_results["L2"]
        assert l2r["continuation_allowed"] is True

    def test_upstream_injection_l2_to_l3(self):
        """L2 result's continuation_allowed is injected into L3 payload."""
        adapter = Phase1RouterEvaluatorAdapter()
        l3 = _l3_pass_payload()
        del l3["upstream_l2_continuation_allowed"]
        result = adapter.run(_l1_pass_payload(), _l2_pass_payload(), l3)
        assert result.halted is False


class TestPhase1EvaluatorChainWarn:
    def test_warn_propagation(self):
        adapter = Phase1RouterEvaluatorAdapter()
        # L1 with degraded state → WARN
        l1 = _l1_pass_payload()
        l1["freshness_state"] = "STALE_PRESERVED"
        l1["warmup_state"] = "PARTIAL"
        l1["fallback_class"] = "LEGAL_EMERGENCY_PRESERVE"
        l1["fallback_used"] = True
        l1["coherence_score"] = 0.74

        result = adapter.run(l1, _l2_pass_payload(), _l3_pass_payload())
        assert result.chain_status == "WARN"
        assert result.continuation_allowed is True


class TestBuildPhase1Payloads:
    def test_build_phase1_payloads(self):
        envelope = {
            "L1": _l1_pass_payload(),
            "L2": _l2_pass_payload(),
            "L3": _l3_pass_payload(),
        }
        l1, l2, l3 = build_phase1_payloads_from_dict(envelope)
        assert l1["input_ref"] == _REF
        assert l2["alignment_score"] == 0.89
        assert l3["confirmation_score"] == 0.88
