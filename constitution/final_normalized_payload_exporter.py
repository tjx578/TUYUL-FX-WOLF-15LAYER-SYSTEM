from __future__ import annotations

"""
Final normalized payload exporter for the constitutional pipeline up to Phase 5.

Converts EndToEndPhase5Result into a flat, auditable, replay-friendly payload
conforming to FINAL_NORMALIZED_PAYLOAD_V1 schema.

Analysis-only exporter. No live execution authority.
"""

import json  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402


@dataclass(frozen=True)
class FinalNormalizedPayload:
    schema: str
    schema_version: str
    input_ref: str
    timestamp: str
    pipeline: dict[str, Any]
    phase_status: dict[str, str]
    verdict: dict[str, Any]
    layer_status: dict[str, str]
    scores: dict[str, float | None]
    blockers: list[str]
    warnings: list[str]
    trace: dict[str, Any]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "input_ref": self.input_ref,
            "timestamp": self.timestamp,
            "pipeline": self.pipeline,
            "phase_status": self.phase_status,
            "verdict": self.verdict,
            "layer_status": self.layer_status,
            "scores": self.scores,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "trace": self.trace,
            "audit": self.audit,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class FinalNormalizedPayloadExporter:
    VERSION = "1.0.0"

    @staticmethod
    def _extract_meta(end_to_end_phase5_result: dict[str, Any]) -> tuple[str, str]:
        input_ref = str(end_to_end_phase5_result.get("input_ref", "")).strip()
        timestamp = str(end_to_end_phase5_result.get("timestamp", "")).strip()
        if not input_ref or not timestamp:
            raise ValueError("Final export requires non-empty input_ref and timestamp.")
        return input_ref, timestamp

    @staticmethod
    def _safe_get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
        cur: Any = d
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    @staticmethod
    def _collect_phase_status(result: dict[str, Any]) -> dict[str, str]:
        synthesis = result.get("phase5_result", {}).get("synthesis_payload", {})
        phase5 = result.get("phase5_result", {})
        return {
            "PHASE_1": str(synthesis.get("foundation_status", "FAIL")).upper(),
            "PHASE_2": str(synthesis.get("scoring_status", "FAIL")).upper(),
            "PHASE_2_5": str(synthesis.get("enrichment_status", "WARN")).upper(),
            "PHASE_3": str(synthesis.get("structure_status", "FAIL")).upper(),
            "PHASE_4": str(synthesis.get("risk_chain_status", "FAIL")).upper(),
            "PHASE_5": str(phase5.get("phase_status", "FAIL")).upper(),
        }

    def _collect_layer_status(self, result: dict[str, Any]) -> dict[str, str]:
        layer_status: dict[str, str] = {}

        upstream = result.get("upstream_result", {})
        phase3 = upstream.get("upstream_result", {})
        foundation_scoring = phase3.get("upstream_result", {})
        foundation = foundation_scoring.get("upstream_result", {})

        phase1_layers = self._safe_get(foundation, "phase_results", "PHASE_1", "summary_status", default={}) or {}
        phase2_layers = self._safe_get(foundation, "phase_results", "PHASE_2", "summary_status", default={}) or {}
        phase3_layers = self._safe_get(phase3, "phase3_result", "summary_status", default={}) or {}
        phase4_layers = self._safe_get(upstream, "phase4_result", "summary_status", default={}) or {}
        l12 = self._safe_get(result, "phase5_result", "l12_result", "verdict_status", default="FAIL")

        layer_status.update({k: str(v).upper() for k, v in phase1_layers.items()})
        layer_status.update({k: str(v).upper() for k, v in phase2_layers.items()})
        layer_status.update({k: str(v).upper() for k, v in phase3_layers.items()})
        layer_status.update({k: str(v).upper() for k, v in phase4_layers.items()})
        layer_status["L12"] = str(l12).upper()
        return layer_status

    def _collect_scores(self, result: dict[str, Any]) -> dict[str, float | None]:
        scores: dict[str, float | None] = {
            k: None for k in ["L1", "L2", "L3", "L4", "L5", "L7", "L8", "L9", "L11", "L6", "L10", "L12"]
        }

        upstream = result.get("upstream_result", {})
        phase3 = upstream.get("upstream_result", {})
        foundation_scoring = phase3.get("upstream_result", {})
        foundation = foundation_scoring.get("upstream_result", {})

        for phase_name in ("PHASE_1", "PHASE_2"):
            layer_results = self._safe_get(foundation, "phase_results", phase_name, "layer_results", default={}) or {}
            for layer_name, layer in layer_results.items():
                val = layer.get("score_numeric")
                if isinstance(val, (int, float)):
                    scores[layer_name] = float(val)

        phase3_layers = self._safe_get(phase3, "phase3_result", "layer_results", default={}) or {}
        for layer_name, layer in phase3_layers.items():
            val = layer.get("score_numeric")
            if isinstance(val, (int, float)):
                scores[layer_name] = float(val)

        phase4_layers = self._safe_get(upstream, "phase4_result", "layer_results", default={}) or {}
        for layer_name, layer in phase4_layers.items():
            val = layer.get("score_numeric")
            if isinstance(val, (int, float)):
                scores[layer_name] = float(val)

        l12_score = self._safe_get(result, "phase5_result", "l12_result", "score_numeric", default=None)
        if isinstance(l12_score, (int, float)):
            scores["L12"] = float(l12_score)

        return scores

    def _collect_blockers_warnings(self, result: dict[str, Any]) -> tuple[list[str], list[str]]:
        blockers: list[str] = []
        warnings: list[str] = []

        upstream = result.get("upstream_result", {})
        phase3 = upstream.get("upstream_result", {})
        foundation_scoring = phase3.get("upstream_result", {})
        foundation = foundation_scoring.get("upstream_result", {})

        for phase_name in ("PHASE_1", "PHASE_2"):
            phase = self._safe_get(foundation, "phase_results", phase_name, default={}) or {}
            blocker_map = phase.get("blocker_map", {}) or {}
            warning_map = phase.get("warning_map", {}) or {}
            for vals in blocker_map.values():
                blockers.extend([str(x) for x in vals])
            for vals in warning_map.values():
                warnings.extend([str(x) for x in vals])

        for phase_key in ("phase3_result", "phase4_result"):
            # phase3_result is nested under upstream.upstream_result
            if phase_key == "phase3_result":
                phase = self._safe_get(phase3, phase_key, default={}) or {}
            else:
                phase = self._safe_get(upstream, phase_key, default={}) or {}
            blocker_map = phase.get("blocker_map", {}) or {}
            warning_map = phase.get("warning_map", {}) or {}
            for vals in blocker_map.values():
                blockers.extend([str(x) for x in vals])
            for vals in warning_map.values():
                warnings.extend([str(x) for x in vals])

        l12 = self._safe_get(result, "phase5_result", "l12_result", default={}) or {}
        blockers.extend([str(x) for x in l12.get("blocker_codes", [])])
        warnings.extend([str(x) for x in l12.get("warning_codes", [])])

        # Dedupe preserve order
        blockers = list(dict.fromkeys([b for b in blockers if b]))
        warnings = list(dict.fromkeys([w for w in warnings if w]))
        return blockers, warnings

    def export(self, end_to_end_phase5_result: dict[str, Any]) -> FinalNormalizedPayload:
        input_ref, timestamp = self._extract_meta(end_to_end_phase5_result)
        phase_status = self._collect_phase_status(end_to_end_phase5_result)
        layer_status = self._collect_layer_status(end_to_end_phase5_result)
        scores = self._collect_scores(end_to_end_phase5_result)
        blockers, warnings = self._collect_blockers_warnings(end_to_end_phase5_result)

        l12_result = self._safe_get(end_to_end_phase5_result, "phase5_result", "l12_result", default={}) or {}

        pipeline = {
            "status": str(end_to_end_phase5_result.get("wrapper_status", "FAIL")).upper(),
            "final_verdict": str(end_to_end_phase5_result.get("final_verdict", "NO_TRADE")).upper(),
            "final_verdict_status": str(end_to_end_phase5_result.get("final_verdict_status", "FAIL")).upper(),
            "continuation_allowed": bool(end_to_end_phase5_result.get("continuation_allowed", False)),
            "next_legal_targets": list(end_to_end_phase5_result.get("next_legal_targets", [])),
        }

        verdict = {
            "verdict": str(l12_result.get("verdict", "NO_TRADE")).upper(),
            "verdict_status": str(l12_result.get("verdict_status", "FAIL")).upper(),
            "synthesis_score": float(l12_result.get("score_numeric", 0.0)),
            "gate_summary": dict(l12_result.get("gate_summary", {})),
        }

        trace = {
            "upstream_result": end_to_end_phase5_result.get("upstream_result", {}),
            "phase5_result": end_to_end_phase5_result.get("phase5_result", {}),
        }

        audit = {
            "exporter_version": self.VERSION,
            "source_wrapper": end_to_end_phase5_result.get("wrapper", ""),
            "source_wrapper_version": end_to_end_phase5_result.get("wrapper_version", ""),
            "notes": [
                "Final normalized payload is analysis-only.",
                "L12 remains the sole verdict authority.",
                "This payload is suitable for export, replay, audit, and governance ingestion.",
            ],
        }

        return FinalNormalizedPayload(
            schema="FINAL_NORMALIZED_PAYLOAD_V1",
            schema_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            pipeline=pipeline,
            phase_status=phase_status,
            verdict=verdict,
            layer_status=layer_status,
            scores=scores,
            blockers=blockers,
            warnings=warnings,
            trace=trace,
            audit=audit,
        )


def export_final_normalized_payload_json(end_to_end_phase5_result: dict[str, Any], indent: int = 2) -> str:
    exporter = FinalNormalizedPayloadExporter()
    payload = exporter.export(end_to_end_phase5_result)
    return payload.to_json(indent=indent)
