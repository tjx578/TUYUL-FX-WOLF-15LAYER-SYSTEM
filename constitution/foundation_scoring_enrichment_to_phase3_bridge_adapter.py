from __future__ import annotations

"""
Foundation+Scoring+Enrichment -> Phase 3 Bridge Adapter
Strict constitutional prototype

Bridges the output of the upstream wrapper
(Foundation -> Scoring -> Enrichment) into legal payloads for Phase 3:
L7 -> L8 -> L9

Analysis-only module. No execution authority.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402


@dataclass(frozen=True)
class UpstreamToPhase3BridgeResult:
    bridge: str
    bridge_version: str
    input_ref: str
    timestamp: str
    bridge_allowed: bool
    bridge_status: str
    next_legal_targets: list[str]
    l7_payload: dict[str, Any]
    l8_payload: dict[str, Any]
    l9_payload: dict[str, Any]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bridge": self.bridge,
            "bridge_version": self.bridge_version,
            "input_ref": self.input_ref,
            "timestamp": self.timestamp,
            "bridge_allowed": self.bridge_allowed,
            "bridge_status": self.bridge_status,
            "next_legal_targets": self.next_legal_targets,
            "l7_payload": self.l7_payload,
            "l8_payload": self.l8_payload,
            "l9_payload": self.l9_payload,
            "audit": self.audit,
        }


class FoundationScoringEnrichmentToPhase3BridgeAdapter:
    VERSION = "1.0.0"

    def __init__(
        self,
        default_probability_sources: list[str] | None = None,
        default_integrity_sources: list[str] | None = None,
        default_structure_sources: list[str] | None = None,
    ) -> None:
        self.default_probability_sources = default_probability_sources or ["monte_carlo", "edge_validator"]
        self.default_integrity_sources = default_integrity_sources or ["tii_engine", "twms_engine"]
        self.default_structure_sources = default_structure_sources or ["smc_engine", "timing_engine"]

    @staticmethod
    def _extract_meta(upstream_result: dict[str, Any]) -> tuple[str, str]:
        input_ref = str(upstream_result.get("input_ref", "")).strip()
        timestamp = str(upstream_result.get("timestamp", "")).strip()
        if not input_ref or not timestamp:
            raise ValueError("Upstream wrapper result must contain non-empty input_ref and timestamp.")
        return input_ref, timestamp

    @staticmethod
    def _is_bridgeable(upstream_result: dict[str, Any]) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        if bool(upstream_result.get("halted", False)):
            reasons.append("UPSTREAM_HALTED")
        if not bool(upstream_result.get("continuation_allowed", False)):
            reasons.append("UPSTREAM_CONTINUATION_DISALLOWED")

        next_targets = [str(x) for x in upstream_result.get("next_legal_targets", [])]
        if "PHASE_3" not in next_targets:
            reasons.append("UPSTREAM_NEXT_TARGET_NOT_PHASE_3")

        wrapper_status = str(upstream_result.get("wrapper_status", "")).upper().strip()
        if wrapper_status not in {"PASS", "WARN"}:
            reasons.append("UPSTREAM_STATUS_NOT_BRIDGEABLE")

        phase25_result = upstream_result.get("phase25_result", {})
        if phase25_result:
            phase25_status = str(phase25_result.get("phase_status", "")).upper().strip()
            if phase25_status not in {"PASS", "WARN"}:
                reasons.append("PHASE25_STATUS_NOT_BRIDGEABLE")

        return (len(reasons) == 0, reasons)

    @staticmethod
    def _derive_freshness_state(upstream_result: dict[str, Any]) -> str:
        candidates: list[str] = []

        upstream_inner = upstream_result.get("upstream_result", {})
        phase_results = upstream_inner.get("phase_results", {})
        for phase_name in ("PHASE_1", "PHASE_2"):
            phase = phase_results.get(phase_name, {})
            layer_results = phase.get("layer_results", {})
            for layer in layer_results.values():
                state = str(layer.get("freshness_state", "")).upper().strip()
                if state:
                    candidates.append(state)

        bridge_result = upstream_inner.get("bridge_result", {})
        for key in ("l4_payload", "l5_payload"):
            payload = bridge_result.get(key, {})
            state = str(payload.get("freshness_state", "")).upper().strip()
            if state:
                candidates.append(state)

        phase25 = upstream_result.get("phase25_result", {})
        if phase25.get("phase_status") == "WARN":
            candidates.append("STALE_PRESERVED")

        priority = ["NO_PRODUCER", "DEGRADED", "STALE_PRESERVED", "FRESH"]
        for state in priority:
            if state in candidates:
                return state
        return "FRESH"

    @staticmethod
    def _derive_warmup_state(upstream_result: dict[str, Any]) -> str:
        candidates: list[str] = []

        upstream_inner = upstream_result.get("upstream_result", {})
        phase_results = upstream_inner.get("phase_results", {})
        for phase_name in ("PHASE_1", "PHASE_2"):
            phase = phase_results.get(phase_name, {})
            layer_results = phase.get("layer_results", {})
            for layer in layer_results.values():
                state = str(layer.get("warmup_state", "")).upper().strip()
                if state:
                    candidates.append(state)

        bridge_result = upstream_inner.get("bridge_result", {})
        for key in ("l4_payload", "l5_payload"):
            payload = bridge_result.get(key, {})
            state = str(payload.get("warmup_state", "")).upper().strip()
            if state:
                candidates.append(state)

        phase25 = upstream_result.get("phase25_result", {})
        if phase25.get("phase_status") == "WARN":
            candidates.append("PARTIAL")

        priority = ["INSUFFICIENT", "PARTIAL", "READY"]
        for state in priority:
            if state in candidates:
                return state
        return "READY"

    @staticmethod
    def _derive_fallback_class(upstream_result: dict[str, Any]) -> str:
        candidates: list[str] = []

        upstream_inner = upstream_result.get("upstream_result", {})
        phase_results = upstream_inner.get("phase_results", {})
        for phase_name in ("PHASE_1", "PHASE_2"):
            phase = phase_results.get(phase_name, {})
            layer_results = phase.get("layer_results", {})
            for layer in layer_results.values():
                value = str(layer.get("fallback_class", "")).upper().strip()
                if value:
                    candidates.append(value)

        bridge_result = upstream_inner.get("bridge_result", {})
        for key in ("l4_payload", "l5_payload"):
            payload = bridge_result.get(key, {})
            value = str(payload.get("fallback_class", "")).upper().strip()
            if value:
                candidates.append(value)

        phase25 = upstream_result.get("phase25_result", {})
        if phase25.get("phase_status") == "WARN":
            advisory = phase25.get("advisory_result", {})
            if advisory.get("status") == "partial":
                candidates.append("LEGAL_EMERGENCY_PRESERVE")

        priority = [
            "ILLEGAL_FALLBACK",
            "LEGAL_EMERGENCY_PRESERVE",
            "LEGAL_PRIMARY_SUBSTITUTE",
            "NO_FALLBACK",
        ]
        for value in priority:
            if value in candidates:
                return value
        return "NO_FALLBACK"

    @staticmethod
    def _warning_pressure(upstream_result: dict[str, Any]) -> dict[str, bool]:
        phase25 = upstream_result.get("phase25_result", {})
        warnings = [str(x).upper() for x in phase25.get("warning_list", [])]
        errors = [str(x).upper() for x in phase25.get("error_list", [])]
        wrapper_status = str(upstream_result.get("wrapper_status", "")).upper().strip()

        return {
            "upstream_warn": wrapper_status == "WARN",
            "phase25_warn": str(phase25.get("phase_status", "")).upper().strip() == "WARN",
            "has_engine_error": len(errors) > 0,
            "has_engine_warning": len(warnings) > 0,
        }

    @staticmethod
    def _derive_l7_score(upstream_result: dict[str, Any], pressure: dict[str, bool]) -> float:
        phase25 = upstream_result.get("phase25_result", {})
        advisory = phase25.get("advisory_result", {})
        outputs = advisory.get("outputs", {})
        failed_count = int(outputs.get("failed_count", 0) or 0)
        partial_count = int(outputs.get("partial_count", 0) or 0)

        if not pressure["upstream_warn"] and not pressure["phase25_warn"] and failed_count == 0:
            return 0.71
        if failed_count > 0 or partial_count > 0 or pressure["has_engine_error"]:
            return 0.60
        if pressure["upstream_warn"] or pressure["phase25_warn"]:
            return 0.60
        return 0.67

    @staticmethod
    def _derive_l8_score(upstream_result: dict[str, Any], pressure: dict[str, bool]) -> float:
        if pressure["has_engine_error"]:
            return 0.80
        if pressure["upstream_warn"] or pressure["phase25_warn"] or pressure["has_engine_warning"]:
            return 0.80
        return 0.91

    @staticmethod
    def _derive_l9_score(upstream_result: dict[str, Any], pressure: dict[str, bool]) -> float:
        if pressure["has_engine_error"]:
            return 0.70
        if pressure["upstream_warn"] or pressure["phase25_warn"] or pressure["has_engine_warning"]:
            return 0.70
        return 0.84

    def build(self, upstream_result: dict[str, Any]) -> UpstreamToPhase3BridgeResult:
        input_ref, timestamp = self._extract_meta(upstream_result)
        allowed, reasons = self._is_bridgeable(upstream_result)

        if not allowed:
            return UpstreamToPhase3BridgeResult(
                bridge="FOUNDATION_SCORING_ENRICHMENT_TO_PHASE3",
                bridge_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                bridge_allowed=False,
                bridge_status="FAIL",
                next_legal_targets=[],
                l7_payload={},
                l8_payload={},
                l9_payload={},
                audit={
                    "bridge_reasons": reasons,
                    "notes": ["Upstream wrapper is not legally bridgeable into Phase 3."],
                },
            )

        freshness_state = self._derive_freshness_state(upstream_result)
        warmup_state = self._derive_warmup_state(upstream_result)
        fallback_class = self._derive_fallback_class(upstream_result)
        pressure = self._warning_pressure(upstream_result)

        l7_score = self._derive_l7_score(upstream_result, pressure)
        l8_score = self._derive_l8_score(upstream_result, pressure)
        l9_score = self._derive_l9_score(upstream_result, pressure)

        # L7
        l7_payload = {
            "input_ref": input_ref,
            "timestamp": timestamp,
            "upstream_continuation_allowed": True,
            "probability_sources_used": list(self.default_probability_sources),
            "required_probability_sources": [self.default_probability_sources[0]],
            "available_probability_sources": list(self.default_probability_sources),
            "win_probability": l7_score,
            "profit_factor": 1.8 if l7_score >= 0.67 else 1.3,
            "sample_count": 80 if not pressure["phase25_warn"] else 20,
            "edge_validation_available": True,
            "edge_status": "VALID" if l7_score >= 0.67 else "DEGRADED",
            "validation_partial": pressure["phase25_warn"] or pressure["has_engine_warning"],
            "fallback_class": fallback_class,
            "freshness_state": freshness_state,
            "warmup_state": warmup_state,
        }

        # L8
        l8_payload = {
            "input_ref": input_ref,
            "timestamp": timestamp,
            "upstream_l7_continuation_allowed": True,
            "integrity_sources_used": list(self.default_integrity_sources),
            "required_integrity_sources": [self.default_integrity_sources[0]],
            "available_integrity_sources": list(self.default_integrity_sources),
            "integrity_score": l8_score,
            "tii_available": True,
            "twms_available": True,
            "integrity_state": "VALID" if l8_score >= 0.88 else "DEGRADED",
            "tii_partial": pressure["phase25_warn"] or pressure["has_engine_warning"],
            "twms_partial": pressure["phase25_warn"] or pressure["has_engine_warning"],
            "governance_degraded": pressure["phase25_warn"] or pressure["upstream_warn"],
            "stability_non_ideal": pressure["phase25_warn"] or pressure["has_engine_error"],
            "fallback_class": fallback_class,
            "freshness_state": freshness_state,
            "warmup_state": warmup_state,
        }

        # L9
        l9_payload = {
            "input_ref": input_ref,
            "timestamp": timestamp,
            "upstream_l8_continuation_allowed": True,
            "structure_sources_used": list(self.default_structure_sources),
            "required_structure_sources": [self.default_structure_sources[0]],
            "available_structure_sources": list(self.default_structure_sources),
            "structure_score": l9_score,
            "structure_alignment_valid": True,
            "entry_timing_available": True,
            "liquidity_state": "VALID" if l9_score >= 0.80 else "DEGRADED",
            "entry_timing_degraded": pressure["phase25_warn"] or pressure["has_engine_warning"],
            "liquidity_partial": pressure["phase25_warn"] or pressure["has_engine_error"],
            "structure_non_ideal": pressure["upstream_warn"] or pressure["phase25_warn"],
            "fallback_class": fallback_class,
            "freshness_state": freshness_state,
            "warmup_state": warmup_state,
        }

        bridge_status = "WARN" if (pressure["upstream_warn"] or pressure["phase25_warn"] or pressure["has_engine_error"] or pressure["has_engine_warning"]) else "PASS"

        return UpstreamToPhase3BridgeResult(
            bridge="FOUNDATION_SCORING_ENRICHMENT_TO_PHASE3",
            bridge_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            bridge_allowed=True,
            bridge_status=bridge_status,
            next_legal_targets=["L7", "L8", "L9"],
            l7_payload=l7_payload,
            l8_payload=l8_payload,
            l9_payload=l9_payload,
            audit={
                "bridge_reasons": ["UPSTREAM_BRIDGEABLE"],
                "derived": {
                    "freshness_state": freshness_state,
                    "warmup_state": warmup_state,
                    "fallback_class": fallback_class,
                    "pressure": pressure,
                    "l7_score": l7_score,
                    "l8_score": l8_score,
                    "l9_score": l9_score,
                },
                "notes": ["Phase 3 payloads derived from upstream wrapper under strict constitutional mode."],
            },
        )
