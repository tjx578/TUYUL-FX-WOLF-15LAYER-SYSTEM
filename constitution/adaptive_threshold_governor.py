from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from core.core_fusion.adaptive_threshold import AdaptiveThresholdController

AdaptiveMode = Literal["force_base", "shadow", "canary", "live"]


class SupportsAdaptiveThresholdController(Protocol):
    def recompute(self, frpc_data: dict[str, Any] | None = None) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AdjustedThreshold:
    layer: str
    metric: str
    base: float
    adjusted: float
    adjustment_factor: float
    mode: AdaptiveMode
    source_completeness: float
    decision_reason: str
    audit_id: str
    audit_signature: str
    controller_reason: str
    freeze_thresholds: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdaptiveThresholdGovernor:
    """Single sanctioned gateway for runtime threshold adjustments.

    PR-5 is shadow-mode only: adjustments are computed and audited, but they do
    not affect constitutional verdicts unless mode is explicitly promoted to
    ``live``. Missing source completeness and controller freeze conditions always
    keep the base threshold.
    """

    VERSION = "1.0.0"
    DAILY_DELTA_BUDGET = 0.08
    SOURCE_COMPLETENESS_MIN = 0.80
    _VALID_MODES: tuple[AdaptiveMode, ...] = ("force_base", "shadow", "canary", "live")

    def __init__(
        self,
        *,
        controller: SupportsAdaptiveThresholdController | None = None,
        mode: AdaptiveMode | None = None,
        daily_delta_budget: float = DAILY_DELTA_BUDGET,
    ) -> None:
        self._controller = controller or AdaptiveThresholdController()
        resolved_mode: AdaptiveMode = mode if mode is not None else self._read_mode_from_env()
        self._mode: AdaptiveMode = resolved_mode
        self._daily_delta_budget = float(daily_delta_budget)

    def _read_mode_from_env(self) -> AdaptiveMode:
        raw = str(os.getenv("ADAPTIVE_THRESHOLD_MODE", "shadow")).strip().lower()
        if raw in self._VALID_MODES:
            return cast(AdaptiveMode, raw)
        return "shadow"

    def _resolve_mode(self, layer: str, metric: str) -> AdaptiveMode:
        scoped_name = f"ADAPTIVE_THRESHOLD_MODE_{layer}_{metric}".upper()
        scoped = str(os.getenv(scoped_name, "")).strip().lower()
        if scoped in self._VALID_MODES:
            return cast(AdaptiveMode, scoped)
        return cast(AdaptiveMode, self._mode)

    def _budget_ok(self, adjustment_factor: float) -> bool:
        delta = abs(float(adjustment_factor) - 1.0)
        return delta <= (self._daily_delta_budget + 1e-9)

    def _sign_payload(self, payload: dict[str, Any]) -> tuple[str, str]:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        signature = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return signature[:16], signature

    def _coerce_frpc_data(self, frpc_data: dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(frpc_data, dict):
            return frpc_data
        return {}

    def _build_result(
        self,
        *,
        layer: str,
        metric: str,
        base_threshold: float,
        adjusted_threshold: float,
        adjustment_factor: float,
        mode: AdaptiveMode,
        source_completeness: float,
        decision_reason: str,
        controller_reason: str,
        freeze_thresholds: bool,
        frpc_data: dict[str, Any],
    ) -> AdjustedThreshold:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "governor_version": self.VERSION,
            "layer": layer,
            "metric": metric,
            "base": round(float(base_threshold), 6),
            "adjusted": round(float(adjusted_threshold), 6),
            "adjustment_factor": round(float(adjustment_factor), 6),
            "mode": mode,
            "source_completeness": round(float(source_completeness), 4),
            "decision_reason": decision_reason,
            "controller_reason": controller_reason,
            "freeze_thresholds": freeze_thresholds,
            "frpc_data": frpc_data,
        }
        audit_id, audit_signature = self._sign_payload(payload)
        return AdjustedThreshold(
            layer=layer,
            metric=metric,
            base=round(float(base_threshold), 6),
            adjusted=round(float(adjusted_threshold), 6),
            adjustment_factor=round(float(adjustment_factor), 6),
            mode=mode,
            source_completeness=round(float(source_completeness), 4),
            decision_reason=decision_reason,
            audit_id=audit_id,
            audit_signature=audit_signature,
            controller_reason=controller_reason,
            freeze_thresholds=freeze_thresholds,
        )

    def get_adjusted(
        self,
        *,
        layer: str,
        metric: str,
        base_threshold: float,
        frpc_data: dict[str, Any] | None,
        source_completeness: float,
        regime_tag: str | None = None,
    ) -> AdjustedThreshold:
        del regime_tag
        mode = self._resolve_mode(layer, metric)
        frpc_payload = self._coerce_frpc_data(frpc_data)
        update = self._controller.recompute(frpc_payload)
        proposed = update.get("proposed", {}) if isinstance(update, dict) else {}
        adjustment_factor = float(proposed.get("adjustment_factor", 1.0))
        controller_reason = str(update.get("reason", "ok")) if isinstance(update, dict) else "ok"
        freeze_thresholds = bool(update.get("freeze_thresholds", False)) if isinstance(update, dict) else False

        decision_reason = "ok"
        adjusted = float(base_threshold)

        if mode == "force_base":
            decision_reason = "force_base"
        elif source_completeness < self.SOURCE_COMPLETENESS_MIN:
            decision_reason = "source_incomplete"
        elif freeze_thresholds:
            decision_reason = f"controller_freeze:{controller_reason}"
        elif not self._budget_ok(adjustment_factor):
            decision_reason = "daily_budget_exceeded"
        elif mode == "live":
            adjusted = float(base_threshold) * adjustment_factor

        return self._build_result(
            layer=layer,
            metric=metric,
            base_threshold=base_threshold,
            adjusted_threshold=adjusted,
            adjustment_factor=adjustment_factor,
            mode=mode,
            source_completeness=source_completeness,
            decision_reason=decision_reason,
            controller_reason=controller_reason,
            freeze_thresholds=freeze_thresholds,
            frpc_data=frpc_payload,
        )


_DEFAULT_GOVERNOR: AdaptiveThresholdGovernor | None = None


def get_governor() -> AdaptiveThresholdGovernor:
    global _DEFAULT_GOVERNOR
    if _DEFAULT_GOVERNOR is None:
        _DEFAULT_GOVERNOR = AdaptiveThresholdGovernor()
    return _DEFAULT_GOVERNOR


def parse_history_ratio(note: str) -> float:
    """Extract history completeness from notes like ``insufficient_data_5/30``."""
    match = re.search(r"(\d+)\s*/\s*30", str(note))
    if not match:
        return 0.0
    return max(0.0, min(1.0, int(match.group(1)) / 30.0))
