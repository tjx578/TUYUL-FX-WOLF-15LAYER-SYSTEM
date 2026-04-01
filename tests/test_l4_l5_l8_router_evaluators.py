"""Tests for L4/L5/L8 router evaluators, Phase 2 evaluator adapter,
evaluator-based bridge, and evaluator-based wrapper.
"""

from __future__ import annotations

import pytest

# ── Evaluator-based wrapper imports ───────────────────────────────────────
from constitution.foundation_scoring_constitutional_wrapper import (
    FoundationScoringEvaluatorWrapper,
    FoundationScoringWrapperResult,
)

# ── L4 evaluator imports ──────────────────────────────────────────────────
from constitution.l4_router_evaluator import (
    L4BlockerCode,
    L4RouterEvaluator,
    L4Status,
    build_l4_input_from_dict,
)

# ── L5 evaluator imports ──────────────────────────────────────────────────
from constitution.l5_router_evaluator import (
    L5BlockerCode,
    L5RouterEvaluator,
    L5Status,
    build_l5_input_from_dict,
)

# ── L8 evaluator imports ──────────────────────────────────────────────────
from constitution.l8_router_evaluator import (
    L8BlockerCode,
    L8RouterEvaluator,
    L8Status,
    build_l8_input_from_dict,
)

# ── Evaluator-based bridge imports ────────────────────────────────────────
from constitution.phase1_to_phase2_bridge_adapter import (
    Phase1ToPhase2EvaluatorBridgeAdapter,
)

# ── Phase 2 evaluator adapter imports ─────────────────────────────────────
from constitution.phase2_chain_adapter import (
    Phase2RouterEvaluatorAdapter,
    build_phase2_evaluator_payloads_from_dict,
)

# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

TS = "2026-03-28T12:00:00+07:00"
REF = "EURUSD_H1_run_100"


def _l4_pass_payload() -> dict:
    return {
        "input_ref": REF,
        "timestamp": TS,
        "upstream_l3_continuation_allowed": True,
        "session_sources_used": ["session_engine", "expectancy_engine"],
        "required_session_sources": ["session_engine"],
        "available_session_sources": ["session_engine", "expectancy_engine"],
        "session_score": 0.90,
        "session_valid": True,
        "expectancy_available": True,
        "prime_session": True,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


def _l5_pass_payload() -> dict:
    return {
        "input_ref": REF,
        "timestamp": TS,
        "upstream_l4_continuation_allowed": True,
        "psychology_sources_used": ["discipline_engine", "risk_event_feed"],
        "required_psychology_inputs": ["discipline_engine"],
        "available_psychology_inputs": ["discipline_engine", "risk_event_feed"],
        "psychology_score": 0.90,
        "discipline_score": 0.95,
        "fatigue_level": "LOW",
        "focus_level": 0.95,
        "revenge_trading": False,
        "fomo_level": 0.1,
        "emotional_bias": 0.1,
        "risk_event_active": False,
        "caution_event": False,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


def _l8_pass_payload() -> dict:
    return {
        "input_ref": REF,
        "timestamp": TS,
        "upstream_l7_continuation_allowed": True,
        "integrity_sources_used": ["tii_engine", "twms_engine"],
        "required_integrity_sources": ["tii_engine"],
        "available_integrity_sources": ["tii_engine", "twms_engine"],
        "integrity_score": 0.91,
        "tii_available": True,
        "twms_available": True,
        "integrity_state": "VALID",
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1  L4 ROUTER EVALUATOR
# ═══════════════════════════════════════════════════════════════════════════


class TestL4RouterEvaluator:
    def setup_method(self) -> None:
        self.evaluator = L4RouterEvaluator()

    def test_pass_high_score(self) -> None:
        inp = build_l4_input_from_dict(_l4_pass_payload())
        r = self.evaluator.evaluate(inp)
        assert r.status == L4Status.PASS
        assert r.continuation_allowed is True
        assert r.coherence_band == "HIGH"
        assert not r.blocker_codes

    def test_warn_mid_score(self) -> None:
        p = _l4_pass_payload()
        p["session_score"] = 0.72
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.WARN
        assert r.continuation_allowed is True
        assert r.coherence_band == "MID"

    def test_fail_low_score(self) -> None:
        p = _l4_pass_payload()
        p["session_score"] = 0.40
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.FAIL
        assert r.continuation_allowed is False

    def test_fail_upstream_blocked(self) -> None:
        p = _l4_pass_payload()
        p["upstream_l3_continuation_allowed"] = False
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.FAIL
        assert L4BlockerCode.UPSTREAM_L3_NOT_CONTINUABLE.value in r.blocker_codes

    def test_fail_missing_source(self) -> None:
        p = _l4_pass_payload()
        p["required_session_sources"] = ["session_engine", "missing_source"]
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.FAIL
        assert L4BlockerCode.REQUIRED_SESSION_SOURCE_MISSING.value in r.blocker_codes

    def test_fail_no_producer(self) -> None:
        p = _l4_pass_payload()
        p["freshness_state"] = "NO_PRODUCER"
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.FAIL

    def test_fail_warmup_insufficient(self) -> None:
        p = _l4_pass_payload()
        p["warmup_state"] = "INSUFFICIENT"
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.FAIL

    def test_fail_illegal_fallback(self) -> None:
        p = _l4_pass_payload()
        p["fallback_class"] = "ILLEGAL_FALLBACK"
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.FAIL

    def test_fail_session_invalid(self) -> None:
        p = _l4_pass_payload()
        p["session_valid"] = False
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.FAIL

    def test_fail_expectancy_unavailable(self) -> None:
        p = _l4_pass_payload()
        p["expectancy_available"] = False
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.FAIL

    def test_warn_stale_preserved(self) -> None:
        p = _l4_pass_payload()
        p["freshness_state"] = "STALE_PRESERVED"
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.WARN
        assert "STALE_PRESERVED_CONTEXT" in r.warning_codes

    def test_warn_non_prime_session(self) -> None:
        p = _l4_pass_payload()
        p["prime_session"] = False
        r = self.evaluator.evaluate(build_l4_input_from_dict(p))
        assert r.status == L4Status.WARN

    def test_fail_contract_malformed(self) -> None:
        r = self.evaluator.evaluate(build_l4_input_from_dict({"input_ref": "", "timestamp": ""}))
        assert r.status == L4Status.FAIL
        assert L4BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value in r.blocker_codes

    def test_to_dict(self) -> None:
        r = self.evaluator.evaluate(build_l4_input_from_dict(_l4_pass_payload()))
        d = r.to_dict()
        assert d["layer"] == "L4"
        assert d["status"] == "PASS"
        assert isinstance(d["features"], dict)


# ═══════════════════════════════════════════════════════════════════════════
# §2  L5 ROUTER EVALUATOR
# ═══════════════════════════════════════════════════════════════════════════


class TestL5RouterEvaluator:
    def setup_method(self) -> None:
        self.evaluator = L5RouterEvaluator()

    def test_pass_high_score(self) -> None:
        r = self.evaluator.evaluate(build_l5_input_from_dict(_l5_pass_payload()))
        assert r.status == L5Status.PASS
        assert r.continuation_allowed is True
        assert r.coherence_band == "HIGH"

    def test_fail_upstream_blocked(self) -> None:
        p = _l5_pass_payload()
        p["upstream_l4_continuation_allowed"] = False
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.FAIL
        assert L5BlockerCode.UPSTREAM_L4_NOT_CONTINUABLE.value in r.blocker_codes

    def test_fail_discipline_low(self) -> None:
        p = _l5_pass_payload()
        p["discipline_score"] = 0.50
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.FAIL
        assert L5BlockerCode.DISCIPLINE_BELOW_MINIMUM.value in r.blocker_codes

    def test_fail_fatigue_critical(self) -> None:
        p = _l5_pass_payload()
        p["fatigue_level"] = "CRITICAL"
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.FAIL

    def test_fail_focus_critical(self) -> None:
        p = _l5_pass_payload()
        p["focus_level"] = 0.20
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.FAIL
        assert L5BlockerCode.FOCUS_CRITICAL.value in r.blocker_codes

    def test_fail_revenge_trading(self) -> None:
        p = _l5_pass_payload()
        p["revenge_trading"] = True
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.FAIL

    def test_fail_risk_event(self) -> None:
        p = _l5_pass_payload()
        p["risk_event_active"] = True
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.FAIL

    def test_warn_fomo_elevated(self) -> None:
        p = _l5_pass_payload()
        p["fomo_level"] = 0.70
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.WARN
        assert "FOMO_ELEVATED" in r.warning_codes

    def test_warn_emotional_bias(self) -> None:
        p = _l5_pass_payload()
        p["emotional_bias"] = 0.75
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.WARN
        assert "EMOTIONAL_BIAS_ELEVATED" in r.warning_codes

    def test_warn_caution_event(self) -> None:
        p = _l5_pass_payload()
        p["caution_event"] = True
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.WARN
        assert "CAUTION_EVENT_ACTIVE" in r.warning_codes

    def test_warn_fatigue_high(self) -> None:
        p = _l5_pass_payload()
        p["fatigue_level"] = "HIGH"
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.WARN

    def test_fail_low_psychology_score(self) -> None:
        p = _l5_pass_payload()
        p["psychology_score"] = 0.40
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.FAIL

    def test_warn_mid_score(self) -> None:
        p = _l5_pass_payload()
        p["psychology_score"] = 0.72
        r = self.evaluator.evaluate(build_l5_input_from_dict(p))
        assert r.status == L5Status.WARN
        assert r.coherence_band == "MID"

    def test_to_dict(self) -> None:
        r = self.evaluator.evaluate(build_l5_input_from_dict(_l5_pass_payload()))
        d = r.to_dict()
        assert d["layer"] == "L5"
        assert d["status"] == "PASS"


# ═══════════════════════════════════════════════════════════════════════════
# §3  L8 ROUTER EVALUATOR
# ═══════════════════════════════════════════════════════════════════════════


class TestL8RouterEvaluator:
    def setup_method(self) -> None:
        self.evaluator = L8RouterEvaluator()

    def test_pass_high_score(self) -> None:
        r = self.evaluator.evaluate(build_l8_input_from_dict(_l8_pass_payload()))
        assert r.status == L8Status.PASS
        assert r.continuation_allowed is True
        assert r.coherence_band == "HIGH"

    def test_fail_upstream_blocked(self) -> None:
        p = _l8_pass_payload()
        p["upstream_l7_continuation_allowed"] = False
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.FAIL
        assert L8BlockerCode.UPSTREAM_L7_NOT_CONTINUABLE.value in r.blocker_codes

    def test_fail_tii_unavailable(self) -> None:
        p = _l8_pass_payload()
        p["tii_available"] = False
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.FAIL
        assert L8BlockerCode.TII_UNAVAILABLE.value in r.blocker_codes

    def test_fail_twms_unavailable(self) -> None:
        p = _l8_pass_payload()
        p["twms_available"] = False
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.FAIL
        assert L8BlockerCode.TWMS_UNAVAILABLE.value in r.blocker_codes

    def test_fail_integrity_invalid(self) -> None:
        p = _l8_pass_payload()
        p["integrity_state"] = "INVALID"
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.FAIL

    def test_fail_low_score(self) -> None:
        p = _l8_pass_payload()
        p["integrity_score"] = 0.50
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.FAIL
        assert r.continuation_allowed is False

    def test_warn_mid_score(self) -> None:
        p = _l8_pass_payload()
        p["integrity_score"] = 0.80
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.WARN
        assert r.continuation_allowed is True
        assert r.coherence_band == "MID"

    def test_warn_degraded_state(self) -> None:
        p = _l8_pass_payload()
        p["integrity_state"] = "DEGRADED"
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.WARN
        assert "INTEGRITY_STATE_DEGRADED" in r.warning_codes

    def test_warn_tii_partial(self) -> None:
        p = _l8_pass_payload()
        p["tii_partial"] = True
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.WARN
        assert "TII_PARTIAL" in r.warning_codes

    def test_warn_governance_degraded(self) -> None:
        p = _l8_pass_payload()
        p["governance_degraded"] = True
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.WARN

    def test_warn_stability_non_ideal(self) -> None:
        p = _l8_pass_payload()
        p["stability_non_ideal"] = True
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.WARN

    def test_fail_missing_source(self) -> None:
        p = _l8_pass_payload()
        p["required_integrity_sources"] = ["tii_engine", "missing_engine"]
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.FAIL

    def test_fail_illegal_fallback(self) -> None:
        p = _l8_pass_payload()
        p["fallback_class"] = "ILLEGAL_FALLBACK"
        r = self.evaluator.evaluate(build_l8_input_from_dict(p))
        assert r.status == L8Status.FAIL

    def test_to_dict(self) -> None:
        r = self.evaluator.evaluate(build_l8_input_from_dict(_l8_pass_payload()))
        d = r.to_dict()
        assert d["layer"] == "L8"
        assert d["status"] == "PASS"


# ═══════════════════════════════════════════════════════════════════════════
# §4  PHASE 2 ROUTER EVALUATOR ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class TestPhase2RouterEvaluatorAdapter:
    def setup_method(self) -> None:
        self.adapter = Phase2RouterEvaluatorAdapter()

    def test_full_pass(self) -> None:
        r = self.adapter.run(_l4_pass_payload(), _l5_pass_payload())
        assert r.chain_status == "PASS"
        assert r.continuation_allowed is True
        assert r.halted is False
        assert "L4" in r.summary_status
        assert "L5" in r.summary_status

    def test_halt_at_l4(self) -> None:
        p4 = _l4_pass_payload()
        p4["session_score"] = 0.30
        r = self.adapter.run(p4, _l5_pass_payload())
        assert r.chain_status == "FAIL"
        assert r.halted is True
        assert r.halted_at == "L4"
        assert "L5" not in r.summary_status

    def test_halt_at_l5(self) -> None:
        p5 = _l5_pass_payload()
        p5["revenge_trading"] = True
        r = self.adapter.run(_l4_pass_payload(), p5)
        assert r.chain_status == "FAIL"
        assert r.halted is True
        assert r.halted_at == "L5"

    def test_warn_propagation(self) -> None:
        p4 = _l4_pass_payload()
        p4["freshness_state"] = "STALE_PRESERVED"
        r = self.adapter.run(p4, _l5_pass_payload())
        assert r.chain_status == "WARN"
        assert r.continuation_allowed is True

    def test_upstream_injection(self) -> None:
        """L5 receives L4 continuation_allowed flag."""
        p4 = _l4_pass_payload()
        p5 = _l5_pass_payload()
        # L4 PASS → L5 should get upstream_l4_continuation_allowed=True
        r = self.adapter.run(p4, p5)
        l5_result = r.layer_results["L5"]
        assert L5BlockerCode.UPSTREAM_L4_NOT_CONTINUABLE.value not in l5_result["blocker_codes"]

    def test_to_dict(self) -> None:
        r = self.adapter.run(_l4_pass_payload(), _l5_pass_payload())
        d = r.to_dict()
        assert d["phase"] == "PHASE_2_SCORING"
        assert isinstance(d["layer_results"], dict)

    def test_canonicalize_raises_on_empty(self) -> None:
        with pytest.raises(ValueError, match="input_ref"):
            self.adapter.run(
                {"timestamp": TS},
                {"timestamp": TS},
            )

    def test_build_payloads_from_dict(self) -> None:
        payload = {"L4": _l4_pass_payload(), "L5": _l5_pass_payload()}
        l4, l5 = build_phase2_evaluator_payloads_from_dict(payload)
        assert l4["session_score"] == 0.90
        assert l5["psychology_score"] == 0.90

    def test_build_payloads_missing_key(self) -> None:
        with pytest.raises(ValueError, match="Missing"):
            build_phase2_evaluator_payloads_from_dict({"L4": {}})


# ═══════════════════════════════════════════════════════════════════════════
# §5  EVALUATOR-BASED BRIDGE
# ═══════════════════════════════════════════════════════════════════════════


def _phase1_pass_result() -> dict:
    """Simulate a passing Phase 1 evaluator chain result."""
    return {
        "phase": "PHASE_1_FOUNDATION",
        "phase_version": "1.0.0",
        "input_ref": REF,
        "timestamp": TS,
        "halted": False,
        "halted_at": None,
        "continuation_allowed": True,
        "next_legal_targets": ["L4"],
        "chain_status": "PASS",
        "summary_status": {"L1": "PASS", "L2": "PASS", "L3": "PASS"},
        "blocker_map": {"L1": [], "L2": [], "L3": []},
        "warning_map": {"L1": [], "L2": [], "L3": []},
        "layer_results": {
            "L1": {
                "score_numeric": 0.90,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
                "fallback_class": "NO_FALLBACK",
            },
            "L2": {
                "score_numeric": 0.88,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
                "fallback_class": "NO_FALLBACK",
            },
            "L3": {
                "score_numeric": 0.85,
                "freshness_state": "FRESH",
                "warmup_state": "READY",
                "fallback_class": "NO_FALLBACK",
            },
        },
        "audit": {"halt_safe": True, "steps": [], "reason": "Phase 1 completed legally"},
    }


class TestPhase1ToPhase2EvaluatorBridge:
    def setup_method(self) -> None:
        self.bridge = Phase1ToPhase2EvaluatorBridgeAdapter()

    def test_bridge_pass(self) -> None:
        r = self.bridge.build(_phase1_pass_result())
        assert r.bridge_allowed is True
        assert r.bridge_status == "PASS"
        assert "L4" in r.next_legal_targets
        assert r.l4_payload["input_ref"] == REF
        assert r.l5_payload["input_ref"] == REF
        assert r.l4_payload["session_score"] > 0

    def test_bridge_halted_phase1(self) -> None:
        p = _phase1_pass_result()
        p["halted"] = True
        p["continuation_allowed"] = False
        p["chain_status"] = "FAIL"
        p["next_legal_targets"] = []
        r = self.bridge.build(p)
        assert r.bridge_allowed is False
        assert r.bridge_status == "FAIL"

    def test_bridge_warn_chain(self) -> None:
        p = _phase1_pass_result()
        p["chain_status"] = "WARN"
        r = self.bridge.build(p)
        assert r.bridge_allowed is True
        assert r.bridge_status == "WARN"
        # WARN → degraded scoring mode
        assert r.l4_payload["degraded_scoring_mode"] is True
        assert r.l5_payload["fatigue_level"] == "MEDIUM"

    def test_freshness_worst_case(self) -> None:
        p = _phase1_pass_result()
        p["layer_results"]["L2"]["freshness_state"] = "STALE_PRESERVED"
        r = self.bridge.build(p)
        assert r.l4_payload["freshness_state"] == "STALE_PRESERVED"

    def test_warmup_worst_case(self) -> None:
        p = _phase1_pass_result()
        p["layer_results"]["L3"]["warmup_state"] = "PARTIAL"
        r = self.bridge.build(p)
        assert r.l4_payload["warmup_state"] == "PARTIAL"

    def test_fallback_worst_case(self) -> None:
        p = _phase1_pass_result()
        p["layer_results"]["L1"]["fallback_class"] = "LEGAL_EMERGENCY_PRESERVE"
        r = self.bridge.build(p)
        assert r.l4_payload["fallback_class"] == "LEGAL_EMERGENCY_PRESERVE"

    def test_warning_pressure_stale(self) -> None:
        p = _phase1_pass_result()
        p["warning_map"]["L1"] = ["STALE_PRESERVED_CONTEXT"]
        r = self.bridge.build(p)
        assert r.l5_payload["caution_event"] is True

    def test_missing_meta_raises(self) -> None:
        with pytest.raises(ValueError, match="input_ref"):
            self.bridge.build({"input_ref": "", "timestamp": ""})

    def test_to_dict(self) -> None:
        r = self.bridge.build(_phase1_pass_result())
        d = r.to_dict()
        assert d["bridge"] == "PHASE1_TO_PHASE2_EVALUATOR"
        assert isinstance(d["l4_payload"], dict)
        assert isinstance(d["l5_payload"], dict)


# ═══════════════════════════════════════════════════════════════════════════
# §6  EVALUATOR-BASED WRAPPER (E2E)
# ═══════════════════════════════════════════════════════════════════════════


def _l1_pass_evaluator_payload() -> dict:
    return {
        "input_ref": REF,
        "timestamp": TS,
        "context_sources_used": ["tick_pipeline", "regime_service"],
        "market_regime": "TRENDING",
        "dominant_force": "MOMENTUM",
        "coherence_score": 0.90,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


def _l2_pass_evaluator_payload() -> dict:
    return {
        "input_ref": REF,
        "timestamp": TS,
        "upstream_l1_continuation_allowed": True,
        "structure_sources_used": ["MTA_Engine_H4", "MTA_Engine_H1"],
        "required_timeframes": ["H4", "H1"],
        "available_timeframes": ["H4", "H1", "M15"],
        "alignment_score": 0.88,
        "hierarchy_followed": True,
        "aligned": True,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


def _l3_pass_evaluator_payload() -> dict:
    return {
        "input_ref": REF,
        "timestamp": TS,
        "upstream_l2_continuation_allowed": True,
        "trend_sources_used": ["trq3d_engine", "candle_engine"],
        "required_trend_sources": ["trq3d_engine"],
        "available_trend_sources": ["trq3d_engine", "candle_engine"],
        "confirmation_score": 0.85,
        "trend_confirmed": True,
        "structure_conflict": False,
        "freshness_state": "FRESH",
        "warmup_state": "READY",
    }


class TestFoundationScoringEvaluatorWrapper:
    def setup_method(self) -> None:
        self.wrapper = FoundationScoringEvaluatorWrapper()

    def test_full_pass(self) -> None:
        payload = {
            "L1": _l1_pass_evaluator_payload(),
            "L2": _l2_pass_evaluator_payload(),
            "L3": _l3_pass_evaluator_payload(),
        }
        r = self.wrapper.run(payload)
        assert isinstance(r, FoundationScoringWrapperResult)
        assert r.halted is False
        assert r.continuation_allowed is True
        assert "PHASE_1" in r.phase_status
        assert "PHASE_2" in r.phase_status
        assert r.wrapper_status in {"PASS", "WARN"}
        assert r.next_legal_targets == ["PHASE_2_5"]

    def test_halt_at_phase1(self) -> None:
        payload = {
            "L1": {
                "input_ref": REF,
                "timestamp": TS,
                "context_sources_used": ["tick_pipeline"],
                "market_regime": "UNKNOWN",
                "dominant_force": "NONE",
                "coherence_score": 0.10,
                "freshness_state": "NO_PRODUCER",
                "warmup_state": "INSUFFICIENT",
                "required_producer_missing": True,
            },
            "L2": _l2_pass_evaluator_payload(),
            "L3": _l3_pass_evaluator_payload(),
        }
        r = self.wrapper.run(payload)
        assert r.halted is True
        assert r.halted_at == "PHASE_1"
        assert r.continuation_allowed is False

    def test_missing_meta_raises(self) -> None:
        with pytest.raises(ValueError, match="input_ref"):
            self.wrapper.run({"L1": {}, "L2": {}, "L3": {}})

    def test_to_dict(self) -> None:
        payload = {
            "L1": _l1_pass_evaluator_payload(),
            "L2": _l2_pass_evaluator_payload(),
            "L3": _l3_pass_evaluator_payload(),
        }
        r = self.wrapper.run(payload)
        d = r.to_dict()
        assert d["wrapper"] == "FOUNDATION_SCORING_EVALUATOR_WRAPPER"
