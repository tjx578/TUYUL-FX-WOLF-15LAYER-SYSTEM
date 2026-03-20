"""Adaptive Threshold Controller -- dynamic threshold management."""

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ._types import AdaptiveUpdate, DEFAULT_META_DRIFT_FREEZE, DEFAULT_MIN_INTEGRITY
from ._utils import _clamp, _clamp01, _safe_float


class AdaptiveThresholdController:
    """Freezes adaptive thresholds when meta_drift > 0.006."""
    VERSION = "6.0"

    def __init__(self, *, meta_drift_freeze: float = DEFAULT_META_DRIFT_FREEZE,
                 min_integrity: float = DEFAULT_MIN_INTEGRITY) -> None:
        self.meta_drift_freeze = float(meta_drift_freeze)
        self.min_integrity = float(min_integrity)
        self._state: Dict[str, Any] = {}

    def recompute(self, frpc_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ts = datetime.now(timezone.utc).isoformat()
        if not frpc_data:
            return AdaptiveUpdate(timestamp=ts, meta_drift=0.0, integrity_index=1.0,
                mean_energy=0.0, freeze_thresholds=True, reason="FRPC data missing -> freeze", proposed={}).as_dict()

        required = {"gradient", "mean_energy", "integrity_index"}
        if not required.issubset(frpc_data):
            missing = sorted(required - set(frpc_data))
            return AdaptiveUpdate(timestamp=ts, meta_drift=0.0, integrity_index=1.0,
                mean_energy=0.0, freeze_thresholds=True, reason=f"missing fields: {missing}", proposed={}).as_dict()

        try:
            md = abs(_safe_float(frpc_data.get("gradient", 0.0)))
            me = _safe_float(frpc_data.get("mean_energy", 0.0))
            ii = _safe_float(frpc_data.get("integrity_index", 1.0))
        except (TypeError, ValueError):
            return AdaptiveUpdate(timestamp=ts, meta_drift=0.0, integrity_index=1.0,
                mean_energy=0.0, freeze_thresholds=True, reason="invalid numeric fields", proposed={}).as_dict()

        if not all(math.isfinite(v) for v in [md, me, ii]):
            return AdaptiveUpdate(timestamp=ts, meta_drift=0.0, integrity_index=1.0,
                mean_energy=0.0, freeze_thresholds=True, reason="non-finite fields", proposed={}).as_dict()

        md = max(md, 0.0); ii = _clamp01(ii); me = max(me, 0.0)

        freeze, reason = False, "ok"
        if md > self.meta_drift_freeze:
            freeze, reason = True, f"meta_drift={md:.6f} > freeze={self.meta_drift_freeze:.6f}"
        elif ii < self.min_integrity:
            freeze, reason = True, f"integrity_index={ii:.4f} < min_integrity={self.min_integrity:.4f}"

        adj = _clamp(1.0 + (md * 12.0) - (max(0.0, ii - 0.96) * 2.0), 0.85, 1.15)
        proposed = {"adjustment_factor": round(adj, 4), "meta_drift": round(md, 6),
                    "mean_energy": round(me, 6), "integrity_index": round(ii, 6)}

        self._state = AdaptiveUpdate(timestamp=ts, meta_drift=md, integrity_index=ii,
            mean_energy=me, freeze_thresholds=freeze, reason=reason, proposed=proposed).as_dict()
        return self._state

    def get_state(self) -> Dict[str, Any]:
        return self._state.copy()
