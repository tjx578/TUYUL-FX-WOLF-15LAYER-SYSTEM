from __future__ import annotations

"""
End-to-end Phase3 -> Phase4 Bridge Adapter
Strict constitutional prototype

Bridges the output of the end-to-end wrapper up to Phase 3 into legal payloads for
Phase 4 risk chain:
L11 -> L6 -> L10

Analysis-only module. No execution authority.
"""

from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402


@dataclass(frozen=True)
class Phase3ToPhase4BridgeResult:
    bridge: str
    bridge_version: str
    input_ref: str
    timestamp: str
    bridge_allowed: bool
    bridge_status: str
    next_legal_targets: list[str]
    l11_payload: dict[str, Any]
    l6_payload: dict[str, Any]
    l10_payload: dict[str, Any]
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
            "l11_payload": self.l11_payload,
            "l6_payload": self.l6_payload,
            "l10_payload": self.l10_payload,
            "audit": self.audit,
        }


class EndToEndPhase3ToPhase4BridgeAdapter:
    VERSION = "1.0.0"

    def __init__(
        self,
        default_rr_sources: list[str] | None = None,
        default_risk_sources: list[str] | None = None,
        default_sizing_sources: list[str] | None = None,
    ) -> None:
        self.default_rr_sources = default_rr_sources or ["rr_engine", "atr_context"]
        self.default_risk_sources = default_risk_sources or ["account_state", "correlation_engine"]
        self.default_sizing_sources = default_sizing_sources or ["sizing_engine", "risk_geometry"]

    @staticmethod
    def _extract_meta(upstream_result: dict[str, Any]) -> tuple[str, str]:
        input_ref = str(upstream_result.get("input_ref", "")).strip()
        timestamp = str(upstream_result.get("timestamp", "")).strip()
        if not input_ref or not timestamp:
            raise ValueError("Phase 3 wrapper result must contain non-empty input_ref and timestamp.")
        return input_ref, timestamp

    @staticmethod
    def _is_bridgeable(upstream_result: dict[str, Any]) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if bool(upstream_result.get("halted", False)):
            reasons.append("UPSTREAM_HALTED")
        if not bool(upstream_result.get("continuation_allowed", False)):
            reasons.append("UPSTREAM_CONTINUATION_DISALLOWED")

        next_targets = [str(x) for x in upstream_result.get("next_legal_targets", [])]
        if "PHASE_4" not in next_targets:
            reasons.append("UPSTREAM_NEXT_TARGET_NOT_PHASE_4")

        wrapper_status = str(upstream_result.get("wrapper_status", "")).upper().strip()
        if wrapper_status not in {"PASS", "WARN"}:
            reasons.append("UPSTREAM_STATUS_NOT_BRIDGEABLE")

        phase3_result = upstream_result.get("phase3_result", {})
        if phase3_result:
            phase3_status = str(phase3_result.get("chain_status", "")).upper().strip()
            if phase3_status not in {"PASS", "WARN"}:
                reasons.append("PHASE3_STATUS_NOT_BRIDGEABLE")

        return (len(reasons) == 0, reasons)

    @staticmethod
    def _collect_context_candidates(upstream_result: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        freshness: list[str] = []
        warmup: list[str] = []
        fallback: list[str] = []

        # Upstream nested wrapper up to phase 3
        up = upstream_result.get("upstream_result", {})

        # Foundation/scoring wrapper nested in upstream
        foundation = up.get("upstream_result", {})
        phase_results = foundation.get("phase_results", {})
        for phase_name in ("PHASE_1", "PHASE_2"):
            phase = phase_results.get(phase_name, {})
            for layer in phase.get("layer_results", {}).values():
                fs = str(layer.get("freshness_state", "")).upper().strip()
                ws = str(layer.get("warmup_state", "")).upper().strip()
                fb = str(layer.get("fallback_class", "")).upper().strip()
                if fs:
                    freshness.append(fs)
                if ws:
                    warmup.append(ws)
                if fb:
                    fallback.append(fb)

        # Phase 2 bridge payloads
        bridge2 = foundation.get("bridge_result", {})
        for key in ("l4_payload", "l5_payload"):
            payload = bridge2.get(key, {})
            fs = str(payload.get("freshness_state", "")).upper().strip()
            ws = str(payload.get("warmup_state", "")).upper().strip()
            fb = str(payload.get("fallback_class", "")).upper().strip()
            if fs:
                freshness.append(fs)
            if ws:
                warmup.append(ws)
            if fb:
                fallback.append(fb)

        # Phase 2.5 result
        phase25 = up.get("phase25_result", {})
        if str(phase25.get("phase_status", "")).upper() == "WARN":
            freshness.append("STALE_PRESERVED")
            warmup.append("PARTIAL")
            advisory = phase25.get("advisory_result", {})
            if str(advisory.get("status", "")).lower() == "partial":
                fallback.append("LEGAL_EMERGENCY_PRESERVE")

        # Phase 3 bridge payloads
        bridge3 = upstream_result.get("bridge_result", {})
        for key in ("l7_payload", "l8_payload", "l9_payload"):
            payload = bridge3.get(key, {})
            fs = str(payload.get("freshness_state", "")).upper().strip()
            ws = str(payload.get("warmup_state", "")).upper().strip()
            fb = str(payload.get("fallback_class", "")).upper().strip()
            if fs:
                freshness.append(fs)
            if ws:
                warmup.append(ws)
            if fb:
                fallback.append(fb)

        # Phase 3 layer results
        phase3 = upstream_result.get("phase3_result", {})
        for layer in phase3.get("layer_results", {}).values():
            fs = str(layer.get("freshness_state", "")).upper().strip()
            ws = str(layer.get("warmup_state", "")).upper().strip()
            fb = str(layer.get("fallback_class", "")).upper().strip()
            if fs:
                freshness.append(fs)
            if ws:
                warmup.append(ws)
            if fb:
                fallback.append(fb)

        return freshness, warmup, fallback

    def _derive_freshness_state(self, upstream_result: dict[str, Any]) -> str:
        freshness, _, _ = self._collect_context_candidates(upstream_result)
        for state in ["NO_PRODUCER", "DEGRADED", "STALE_PRESERVED", "FRESH"]:
            if state in freshness:
                return state
        return "FRESH"

    def _derive_warmup_state(self, upstream_result: dict[str, Any]) -> str:
        _, warmup, _ = self._collect_context_candidates(upstream_result)
        for state in ["INSUFFICIENT", "PARTIAL", "READY"]:
            if state in warmup:
                return state
        return "READY"

    def _derive_fallback_class(self, upstream_result: dict[str, Any]) -> str:
        _, _, fallback = self._collect_context_candidates(upstream_result)
        for value in ["ILLEGAL_FALLBACK", "LEGAL_EMERGENCY_PRESERVE", "LEGAL_PRIMARY_SUBSTITUTE", "NO_FALLBACK"]:
            if value in fallback:
                return value
        return "NO_FALLBACK"

    @staticmethod
    def _warning_pressure(upstream_result: dict[str, Any]) -> dict[str, bool]:
        wrapper_status = str(upstream_result.get("wrapper_status", "")).upper().strip()
        phase3_result = upstream_result.get("phase3_result", {})
        phase3_status = str(phase3_result.get("chain_status", "")).upper().strip()
        warning_map = phase3_result.get("warning_map", {})
        warnings = []
        for layer in ("L7", "L8", "L9"):
            warnings.extend([str(x).upper() for x in warning_map.get(layer, [])])

        text = " ".join(warnings)
        return {
            "upstream_warn": wrapper_status == "WARN",
            "phase3_warn": phase3_status == "WARN",
            "probability_warn": "EDGE_STATUS_DEGRADED" in text or "VALIDATION_PARTIAL" in text or "LOW_SAMPLE_COUNT" in text,
            "integrity_warn": "INTEGRITY_STATE_DEGRADED" in text or "TII_PARTIAL" in text or "TWMS_PARTIAL" in text,
            "structure_warn": "ENTRY_TIMING_DEGRADED" in text or "LIQUIDITY_PARTIAL" in text or "STRUCTURE_NON_IDEAL" in text,
        }

    @staticmethod
    def _derive_l11_score(pressure: dict[str, bool]) -> float:
        if pressure["upstream_warn"] or pressure["phase3_warn"]:
            return 0.72
        return 0.84

    @staticmethod
    def _derive_l6_score(pressure: dict[str, bool]) -> float:
        if pressure["integrity_warn"] or pressure["structure_warn"] or pressure["upstream_warn"]:
            return 0.75
        return 0.89

    @staticmethod
    def _derive_l10_score(pressure: dict[str, bool]) -> float:
        if pressure["structure_warn"] or pressure["upstream_warn"]:
            return 0.76
        return 0.89

    def build(self, upstream_result: dict[str, Any]) -> Phase3ToPhase4BridgeResult:
        input_ref, timestamp = self._extract_meta(upstream_result)
        bridge_allowed, reasons = self._is_bridgeable(upstream_result)

        if not bridge_allowed:
            return Phase3ToPhase4BridgeResult(
                bridge="PHASE3_TO_PHASE4",
                bridge_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                bridge_allowed=False,
                bridge_status="FAIL",
                next_legal_targets=[],
                l11_payload={},
                l6_payload={},
                l10_payload={},
                audit={
                    "bridge_reasons": reasons,
                    "notes": ["Phase 3 wrapper result is not legally bridgeable into Phase 4."],
                },
            )

        freshness_state = self._derive_freshness_state(upstream_result)
        warmup_state = self._derive_warmup_state(upstream_result)
        fallback_class = self._derive_fallback_class(upstream_result)
        pressure = self._warning_pressure(upstream_result)

        l11_score = self._derive_l11_score(pressure)
        l6_score = self._derive_l6_score(pressure)
        l10_score = self._derive_l10_score(pressure)

        l11_payload = {
            "input_ref": input_ref,
            "timestamp": timestamp,
            "upstream_continuation_allowed": True,
            "rr_sources_used": list(self.default_rr_sources),
            "required_rr_sources": [self.default_rr_sources[0]],
            "available_rr_sources": list(self.default_rr_sources),
            "entry_available": True,
            "stop_loss_available": True,
            "take_profit_available": True,
            "rr_score": l11_score,
            "rr_ratio": 2.1 if l11_score >= 0.80 else 1.4,
            "rr_valid": True,
            "battle_plan_available": True,
            "battle_plan_degraded": pressure["probability_warn"] or pressure["structure_warn"] or pressure["upstream_warn"],
            "atr_context_available": True,
            "atr_context_partial": pressure["upstream_warn"] or pressure["phase3_warn"],
            "target_geometry_non_ideal": pressure["structure_warn"],
            "multi_target_incomplete": pressure["upstream_warn"],
            "fallback_class": fallback_class,
            "freshness_state": freshness_state,
            "warmup_state": warmup_state,
        }

        l6_payload = {
            "input_ref": input_ref,
            "timestamp": timestamp,
            "upstream_l11_continuation_allowed": True,
            "risk_sources_used": list(self.default_risk_sources),
            "required_risk_sources": [self.default_risk_sources[0]],
            "available_risk_sources": list(self.default_risk_sources),
            "firewall_score": l6_score,
            "account_state_available": True,
            "drawdown_pct": 0.02 if l6_score >= 0.85 else 0.06,
            "daily_loss_pct": 0.01 if l6_score >= 0.85 else 0.03,
            "correlation_exposure": 0.30 if l6_score >= 0.85 else 0.60,
            "vol_cluster": "NORMAL" if l6_score >= 0.85 else "HIGH",
            "firewall_state": "VALID" if l6_score >= 0.85 else "DEGRADED",
            "drawdown_elevated": l6_score < 0.85,
            "daily_loss_elevated": l6_score < 0.85,
            "correlation_elevated": l6_score < 0.85,
            "fallback_class": fallback_class,
            "freshness_state": freshness_state,
            "warmup_state": warmup_state,
        }

        l10_payload = {
            "input_ref": input_ref,
            "timestamp": timestamp,
            "upstream_l6_continuation_allowed": True,
            "sizing_sources_used": list(self.default_sizing_sources),
            "required_sizing_sources": [self.default_sizing_sources[0]],
            "available_sizing_sources": list(self.default_sizing_sources),
            "sizing_score": l10_score,
            "entry_available": True,
            "stop_loss_available": True,
            "risk_input_available": True,
            "geometry_valid": True,
            "position_sizing_available": True,
            "compliance_state": "VALID" if l10_score >= 0.85 else "DEGRADED",
            "geometry_non_ideal": l10_score < 0.85,
            "sizing_partial": l10_score < 0.85,
            "account_limit_proximity_elevated": l10_score < 0.85,
            "fallback_class": fallback_class,
            "freshness_state": freshness_state,
            "warmup_state": warmup_state,
        }

        bridge_status = "WARN" if (pressure["upstream_warn"] or pressure["phase3_warn"]) else "PASS"

        return Phase3ToPhase4BridgeResult(
            bridge="PHASE3_TO_PHASE4",
            bridge_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            bridge_allowed=True,
            bridge_status=bridge_status,
            next_legal_targets=["L11", "L6", "L10"],
            l11_payload=l11_payload,
            l6_payload=l6_payload,
            l10_payload=l10_payload,
            audit={
                "bridge_reasons": ["UPSTREAM_BRIDGEABLE"],
                "derived": {
                    "freshness_state": freshness_state,
                    "warmup_state": warmup_state,
                    "fallback_class": fallback_class,
                    "pressure": pressure,
                    "l11_score": l11_score,
                    "l6_score": l6_score,
                    "l10_score": l10_score,
                },
                "notes": ["Phase 4 payloads derived from Phase 3 wrapper under strict constitutional mode."],
            },
        )
