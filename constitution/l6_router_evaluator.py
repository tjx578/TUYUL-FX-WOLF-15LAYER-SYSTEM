from __future__ import annotations

"""
L6 Router Evaluator — strict constitutional prototype

Analysis-only module for capital firewall / correlation-risk legality.
This module does NOT emit execute, trade_valid, sizing, or final verdict.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L6Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L6FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L6WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L6FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L6CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L6BlockerCode(str, Enum):
    UPSTREAM_L11_NOT_CONTINUABLE = "UPSTREAM_L11_NOT_CONTINUABLE"
    REQUIRED_RISK_SOURCE_MISSING = "REQUIRED_RISK_SOURCE_MISSING"
    ACCOUNT_STATE_UNAVAILABLE = "ACCOUNT_STATE_UNAVAILABLE"
    DRAWDOWN_LIMIT_BREACHED = "DRAWDOWN_LIMIT_BREACHED"
    DAILY_LOSS_LIMIT_BREACHED = "DAILY_LOSS_LIMIT_BREACHED"
    CORRELATION_EXPOSURE_EXCEEDED = "CORRELATION_EXPOSURE_EXCEEDED"
    VOL_CLUSTER_EXTREME = "VOL_CLUSTER_EXTREME"
    FIREWALL_STATE_INVALID = "FIREWALL_STATE_INVALID"
    FIREWALL_SCORE_BELOW_MINIMUM = "FIREWALL_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L6Input:
    input_ref: str
    timestamp: str
    upstream_l11_continuation_allowed: bool = True

    risk_sources_used: list[str] = field(default_factory=list)
    required_risk_sources: list[str] = field(default_factory=list)
    available_risk_sources: list[str] = field(default_factory=list)

    firewall_score: float = 0.0
    account_state_available: bool = True
    drawdown_pct: float = 0.0
    daily_loss_pct: float = 0.0
    correlation_exposure: float = 0.0
    vol_cluster: str = "NORMAL"  # LOW | NORMAL | HIGH | EXTREME
    firewall_state: str = "VALID"  # VALID | DEGRADED | INVALID

    drawdown_elevated: bool = False
    daily_loss_elevated: bool = False
    correlation_elevated: bool = False

    fallback_class: L6FallbackClass = L6FallbackClass.NO_FALLBACK
    freshness_state: L6FreshnessState = L6FreshnessState.FRESH
    warmup_state: L6WarmupState = L6WarmupState.READY


@dataclass(frozen=True)
class L6EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L6Status
    continuation_allowed: bool
    blocker_codes: list[str]
    warning_codes: list[str]
    fallback_class: str
    freshness_state: str
    warmup_state: str
    coherence_band: str
    score_numeric: float
    features: dict[str, Any]
    routing: dict[str, Any]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "layer_version": self.layer_version,
            "timestamp": self.timestamp,
            "input_ref": self.input_ref,
            "status": self.status.value,
            "continuation_allowed": self.continuation_allowed,
            "blocker_codes": self.blocker_codes,
            "warning_codes": self.warning_codes,
            "fallback_class": self.fallback_class,
            "freshness_state": self.freshness_state,
            "warmup_state": self.warmup_state,
            "coherence_band": self.coherence_band,
            "score_numeric": self.score_numeric,
            "features": self.features,
            "routing": self.routing,
            "audit": self.audit,
        }


class L6RouterEvaluator:
    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.85
    MID_THRESHOLD = 0.70

    def _score_band(self, firewall_score: float) -> L6CoherenceBand:
        if firewall_score >= self.HIGH_THRESHOLD:
            return L6CoherenceBand.HIGH
        if firewall_score >= self.MID_THRESHOLD:
            return L6CoherenceBand.MID
        return L6CoherenceBand.LOW

    def evaluate(self, payload: L6Input) -> L6EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        if not payload.input_ref or not payload.timestamp:
            blockers.append(L6BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        if not payload.upstream_l11_continuation_allowed:
            blockers.append(L6BlockerCode.UPSTREAM_L11_NOT_CONTINUABLE.value)

        missing_required = sorted(set(payload.required_risk_sources) - set(payload.available_risk_sources))
        if missing_required:
            blockers.append(L6BlockerCode.REQUIRED_RISK_SOURCE_MISSING.value)
            notes.append(f"Missing required risk sources: {', '.join(missing_required)}")

        if payload.freshness_state == L6FreshnessState.NO_PRODUCER:
            blockers.append(L6BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)
        elif payload.freshness_state == L6FreshnessState.STALE_PRESERVED:
            warnings.append("STALE_PRESERVED_CONTEXT")
        elif payload.freshness_state == L6FreshnessState.DEGRADED:
            warnings.append("DEGRADED_CONTEXT")

        if payload.warmup_state == L6WarmupState.INSUFFICIENT:
            blockers.append(L6BlockerCode.WARMUP_INSUFFICIENT.value)
        elif payload.warmup_state == L6WarmupState.PARTIAL:
            warnings.append("PARTIAL_WARMUP")

        if payload.fallback_class == L6FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L6BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)
        elif payload.fallback_class == L6FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
        elif payload.fallback_class == L6FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")

        if not payload.account_state_available:
            blockers.append(L6BlockerCode.ACCOUNT_STATE_UNAVAILABLE.value)

        if payload.drawdown_pct >= 0.10:
            blockers.append(L6BlockerCode.DRAWDOWN_LIMIT_BREACHED.value)
        elif payload.drawdown_elevated:
            warnings.append("DRAWDOWN_ELEVATED")

        if payload.daily_loss_pct >= 0.05:
            blockers.append(L6BlockerCode.DAILY_LOSS_LIMIT_BREACHED.value)
        elif payload.daily_loss_elevated:
            warnings.append("DAILY_LOSS_ELEVATED")

        if payload.correlation_exposure >= 0.80:
            blockers.append(L6BlockerCode.CORRELATION_EXPOSURE_EXCEEDED.value)
        elif payload.correlation_elevated:
            warnings.append("CORRELATION_EXPOSURE_ELEVATED")

        vol_cluster = str(payload.vol_cluster).upper().strip()
        if vol_cluster == "EXTREME":
            blockers.append(L6BlockerCode.VOL_CLUSTER_EXTREME.value)
        elif vol_cluster == "HIGH":
            warnings.append("VOL_CLUSTER_HIGH")

        firewall_state = str(payload.firewall_state).upper().strip()
        if firewall_state == "INVALID":
            blockers.append(L6BlockerCode.FIREWALL_STATE_INVALID.value)
        elif firewall_state == "DEGRADED":
            warnings.append("FIREWALL_STATE_DEGRADED")

        score_band = self._score_band(payload.firewall_score)
        rule_hits.append(f"score_band={score_band.value}")

        status = L6Status.PASS
        continuation_allowed = True
        next_targets = ["L10"]

        if blockers:
            status = L6Status.FAIL
            continuation_allowed = False
            next_targets = []
        elif score_band == L6CoherenceBand.LOW:
            status = L6Status.FAIL
            continuation_allowed = False
            next_targets = []
            blockers.append(L6BlockerCode.FIREWALL_SCORE_BELOW_MINIMUM.value)
        else:
            if (
                payload.freshness_state != L6FreshnessState.FRESH
                or payload.warmup_state != L6WarmupState.READY
                or payload.fallback_class == L6FallbackClass.LEGAL_EMERGENCY_PRESERVE
                or score_band == L6CoherenceBand.MID
                or payload.drawdown_elevated
                or payload.daily_loss_elevated
                or payload.correlation_elevated
                or vol_cluster == "HIGH"
                or firewall_state == "DEGRADED"
            ):
                status = L6Status.WARN

        features = {
            "feature_vector": {
                "firewall_score": round(payload.firewall_score, 4),
                "account_state_available": payload.account_state_available,
                "drawdown_pct": round(payload.drawdown_pct, 4),
                "daily_loss_pct": round(payload.daily_loss_pct, 4),
                "correlation_exposure": round(payload.correlation_exposure, 4),
                "vol_cluster": vol_cluster,
                "firewall_state": firewall_state,
                "drawdown_elevated": payload.drawdown_elevated,
                "daily_loss_elevated": payload.daily_loss_elevated,
                "correlation_elevated": payload.correlation_elevated,
            },
            "feature_hash": f"L6_{score_band.value}_{status.value}_{int(round(payload.firewall_score * 100))}",
        }

        routing = {
            "source_used": list(payload.risk_sources_used),
            "fallback_used": payload.fallback_class != L6FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        return L6EvaluationResult(
            layer="L6",
            layer_version=self.VERSION,
            timestamp=payload.timestamp,
            input_ref=payload.input_ref,
            status=status,
            continuation_allowed=continuation_allowed,
            blocker_codes=list(dict.fromkeys(blockers)),
            warning_codes=list(dict.fromkeys(warnings)),
            fallback_class=payload.fallback_class.value,
            freshness_state=payload.freshness_state.value,
            warmup_state=payload.warmup_state.value,
            coherence_band=score_band.value,
            score_numeric=round(payload.firewall_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l6_input_from_dict(payload: dict[str, Any]) -> L6Input:
    return L6Input(
        input_ref=str(payload.get("input_ref", "")).strip(),
        timestamp=str(payload.get("timestamp", "")).strip(),
        upstream_l11_continuation_allowed=bool(payload.get("upstream_l11_continuation_allowed", True)),
        risk_sources_used=[str(x) for x in payload.get("risk_sources_used", [])],
        required_risk_sources=[str(x) for x in payload.get("required_risk_sources", [])],
        available_risk_sources=[str(x) for x in payload.get("available_risk_sources", payload.get("risk_sources_used", []))],
        firewall_score=float(payload.get("firewall_score", 0.0)),
        account_state_available=bool(payload.get("account_state_available", True)),
        drawdown_pct=float(payload.get("drawdown_pct", 0.0)),
        daily_loss_pct=float(payload.get("daily_loss_pct", 0.0)),
        correlation_exposure=float(payload.get("correlation_exposure", 0.0)),
        vol_cluster=str(payload.get("vol_cluster", "NORMAL")),
        firewall_state=str(payload.get("firewall_state", "VALID")),
        drawdown_elevated=bool(payload.get("drawdown_elevated", False)),
        daily_loss_elevated=bool(payload.get("daily_loss_elevated", False)),
        correlation_elevated=bool(payload.get("correlation_elevated", False)),
        fallback_class=L6FallbackClass(str(payload.get("fallback_class", "NO_FALLBACK"))),
        freshness_state=L6FreshnessState(str(payload.get("freshness_state", "FRESH"))),
        warmup_state=L6WarmupState(str(payload.get("warmup_state", "READY"))),
    )


if __name__ == "__main__":
    evaluator = L6RouterEvaluator()
    examples = [
        {
            "input_ref": "EURUSD_H1_run_910",
            "timestamp": "2026-03-28T17:30:00+07:00",
            "upstream_l11_continuation_allowed": True,
            "risk_sources_used": ["account_state", "correlation_engine"],
            "required_risk_sources": ["account_state"],
            "available_risk_sources": ["account_state", "correlation_engine"],
            "firewall_score": 0.89,
            "account_state_available": True,
            "drawdown_pct": 0.02,
            "daily_loss_pct": 0.01,
            "correlation_exposure": 0.30,
            "vol_cluster": "NORMAL",
            "firewall_state": "VALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
        {
            "input_ref": "EURUSD_H1_run_911",
            "timestamp": "2026-03-28T17:35:00+07:00",
            "upstream_l11_continuation_allowed": True,
            "risk_sources_used": ["account_state", "preserved_corr"],
            "required_risk_sources": ["account_state"],
            "available_risk_sources": ["account_state", "preserved_corr"],
            "firewall_score": 0.75,
            "account_state_available": True,
            "drawdown_pct": 0.06,
            "daily_loss_pct": 0.03,
            "correlation_exposure": 0.60,
            "vol_cluster": "HIGH",
            "firewall_state": "DEGRADED",
            "drawdown_elevated": True,
            "daily_loss_elevated": True,
            "correlation_elevated": True,
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
        },
        {
            "input_ref": "EURUSD_H1_run_912",
            "timestamp": "2026-03-28T17:40:00+07:00",
            "upstream_l11_continuation_allowed": False,
            "risk_sources_used": ["account_state"],
            "required_risk_sources": ["account_state"],
            "available_risk_sources": ["account_state"],
            "firewall_score": 0.50,
            "account_state_available": False,
            "drawdown_pct": 0.12,
            "daily_loss_pct": 0.06,
            "correlation_exposure": 0.90,
            "vol_cluster": "EXTREME",
            "firewall_state": "INVALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
    ]
    for ex in examples:
        print(evaluator.evaluate(build_l6_input_from_dict(ex)).to_dict())
