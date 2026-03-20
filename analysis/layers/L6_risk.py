"""
L6 — CAPITAL FIREWALL RISK ENGINE (v4 PRODUCTION)

Hard authority risk layer.  Can independently block trade even if
L7–L12 say YES.  Executes BEFORE position sizing (L10) and final
verdict (L12).

Responsibilities:
  1. Drawdown-based risk tiering   (LEVEL_0 … LEVEL_4)
  2. Volatility clustering adjustment (EXTREME / HIGH dampening)
  3. Correlation exposure dampener  (corr > 0.7 → reduce risk)
  4. LRCE — Lorentzian Risk Compression Estimator (field instability)
  5. Rolling Sharpe degradation monitor
  6. Kelly fraction dampener under drawdown stress
  7. Prop-firm hard-block enforcement (daily DD, total DD)

Zone: analysis/  — produces risk profile consumed by L10 / L12.
No execution side-effects.

Produces:
  risk_status        (str)   OPTIMAL | CAUTION | WARNING | DEFENSIVE
                              | CRITICAL | CORRELATION_STRESS
                              | UNSTABLE_FIELD | SHARPE_DEGRADATION
                              | DAILY_LIMIT_BREACH | TOTAL_DD_BREACH
  propfirm_compliant (bool)
  drawdown_level     (str)   LEVEL_0 … LEVEL_4
  risk_multiplier    (float) 0.0 – 1.0
  lrce               (float) 0.0 – 1.0  (< 0.6 = stable)
  rolling_sharpe     (float)
  kelly_adjusted     (float)
  max_risk_pct       (float) effective risk cap after all adjustments
  risk_ok            (bool)  False ↔ hard block
  valid              (bool)  always True
"""  # noqa: N999

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["L6RiskAnalyzer"]

# ─────────────────────────────────────────────────────────────────────
# Optional Engine Enrichment (VolClustering / CorrelationRisk)
# ─────────────────────────────────────────────────────────────────────
try:
    from engines.volatility_clustering_model import (
        VolatilityClusteringModel,
    )

    _vol_cluster_model: VolatilityClusteringModel | None = VolatilityClusteringModel()
except Exception:  # pragma: no cover
    _vol_cluster_model = None

try:
    from engines.correlation_risk_engine import (
        CorrelationRiskEngine,
    )

    _corr_engine: CorrelationRiskEngine | None = CorrelationRiskEngine()
except Exception:  # pragma: no cover
    _corr_engine = None


# ─────────────────────────────────────────────────────────────────────
# Config defaults (overridden from config YAML when available)
# ─────────────────────────────────────────────────────────────────────
_DEFAULT_MAX_DAILY_DD = 0.05  # 5%  (prop_firm.yaml: drawdown.max_daily_percent)
_DEFAULT_MAX_TOTAL_DD = 0.10  # 10% (prop_firm.yaml: drawdown.max_total_percent)
_DEFAULT_BASE_RISK_PCT = 0.01  # 1%  (risk.yaml: position_sizing.default_risk_percent)


# ─────────────────────────────────────────────────────────────────────
# L6 Risk Engine
# ─────────────────────────────────────────────────────────────────────


class L6RiskAnalyzer:
    """Layer 6: Capital Firewall Risk Engine (v4 PRODUCTION).

    Backward-compatible with old ``analyze(rr=...)`` signature.
    New callers may also pass ``account_state``, ``enrichment``,
    ``trade_returns``, and ``pair_returns`` for full evaluation.
    """

    def __init__(
        self,
        *,
        sharpe_lookback: int = 50,
        sharpe_degradation_threshold: float = 0.5,
        lrce_block_threshold: float = 0.60,
    ) -> None:
        self.sharpe_lookback = sharpe_lookback
        self.sharpe_degradation_threshold = sharpe_degradation_threshold
        self.lrce_block_threshold = lrce_block_threshold

        # Load limits from config (graceful fallback)
        self._max_daily_dd = _DEFAULT_MAX_DAILY_DD
        self._max_total_dd = _DEFAULT_MAX_TOTAL_DD
        self._base_risk_pct = _DEFAULT_BASE_RISK_PCT
        self._load_config()

    # ────────────────── Config ──────────────────────────────────────

    def _load_config(self) -> None:
        """Read risk limits from project YAML configs."""
        try:
            from config_loader import load_prop_firm, load_risk  # noqa: PLC0415

            pf = load_prop_firm()
            dd = pf.get("drawdown", {})
            self._max_daily_dd = dd.get("max_daily_percent", 5.0) / 100.0
            self._max_total_dd = dd.get("max_total_percent", 10.0) / 100.0

            risk_cfg = load_risk()
            ps = risk_cfg.get("position_sizing", {})
            self._base_risk_pct = ps.get("default_risk_percent", 0.01)

        except Exception as exc:
            logger.warning("[L6] Config load failed, using defaults: %s", exc)

    # ────────────────── Internal Computations ───────────────────────

    @staticmethod
    def _compute_drawdown(equity: float, peak: float) -> float:
        """Fractional drawdown (0.0 – 1.0)."""
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - equity) / peak)

    def _classify_drawdown(
        self,
        current_dd: float,
    ) -> tuple[str, float, str, bool]:
        """Classify drawdown into tier.

        Returns (level, risk_mult, status, hard_block).
        """
        if current_dd >= 0.08:
            return "LEVEL_4", 0.0, "CRITICAL", True
        if current_dd >= 0.06:
            return "LEVEL_3", 0.3, "DEFENSIVE", False
        if current_dd >= 0.04:
            return "LEVEL_2", 0.5, "WARNING", False
        if current_dd >= 0.02:
            return "LEVEL_1", 0.8, "CAUTION", False
        return "LEVEL_0", 1.0, "OPTIMAL", False

    @staticmethod
    def _vol_cluster_multiplier(vol_cluster: str) -> float:
        """Risk multiplier for volatility clustering regime."""
        _map = {
            "EXTREME": 0.5,
            "HIGH": 0.7,
            "NORMAL": 1.0,
            "LOW": 1.0,
            "DEAD": 0.8,
        }
        return _map.get(vol_cluster.upper(), 1.0)

    @staticmethod
    def _correlation_multiplier(corr_exposure: float) -> float:
        """Dampen risk when correlation exposure is elevated."""
        if corr_exposure > 0.7:
            return 0.6
        return 1.0

    def _compute_lrce(self, enrichment: dict[str, float]) -> float:
        """Lorentzian Risk Compression Estimator.

        Measures divergence between structural energy and probability
        coherence.  Returns 0.0 – 1.0.  Values > 0.6 indicate field
        fracture (→ hard block).
        """
        fusion_momentum = float(enrichment.get("fusion_momentum", 0.0))
        quantum_prob = float(enrichment.get("quantum_probability", 0.0))
        bias_strength = float(enrichment.get("bias_strength", 0.0))
        posterior = float(enrichment.get("posterior", 0.0))

        raw = abs(fusion_momentum - quantum_prob) + abs(bias_strength - posterior)
        return min(1.0, raw)

    def _rolling_sharpe(self, returns: list[float]) -> float:
        """Compute rolling Sharpe ratio over last *sharpe_lookback* trades."""
        if len(returns) < self.sharpe_lookback:
            return 0.0

        try:
            import numpy as np  # noqa: PLC0415

            r = np.array(returns[-self.sharpe_lookback :], dtype=np.float64)
            std = float(np.std(r))
            if std == 0:
                return 0.0
            return float(np.mean(r) / std)
        except Exception:
            return 0.0

    @staticmethod
    def _kelly_dampener(base_kelly: float, current_dd: float) -> float:
        """Reduce Kelly fraction under drawdown stress."""
        if current_dd < 0.02:
            return base_kelly
        if current_dd < 0.04:
            return base_kelly * 0.8
        if current_dd < 0.06:
            return base_kelly * 0.6
        if current_dd < 0.08:
            return base_kelly * 0.4
        return 0.0  # freeze under extreme drawdown

    # ────────────────── MAIN ENTRY ──────────────────────────────────

    def analyze(  # noqa: PLR0912
        self,
        *,
        rr: float = 2.0,
        trade_returns: list[float] | None = None,
        pair_returns: dict[str, list[float]] | None = None,
        account_state: dict[str, Any] | None = None,
        enrichment: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Evaluate risk — CAPITAL FIREWALL.

        Backward-compatible: calling ``analyze(rr=2.0)`` still works.
        For full evaluation, pass ``account_state`` and/or ``enrichment``.

        Parameters
        ----------
        rr : float
            Risk-reward ratio (from L11).  Used for advisory flagging.
        trade_returns : list[float] | None
            Historical per-trade P&L for Rolling Sharpe + vol-clustering.
        pair_returns : dict[str, list[float]] | None
            Per-pair return series for correlation risk engine.
        account_state : dict | None
            Keys: ``drawdown_pct`` (float 0–100 or 0–1),
            ``daily_loss_pct`` (float), ``equity`` (float),
            ``peak_equity`` (float), ``consecutive_losses`` (int),
            ``vol_cluster`` (str), ``corr_exposure`` (float),
            ``base_kelly`` (float).
        enrichment : dict | None
            Engine enrichment outputs for LRCE.  Keys:
            ``fusion_momentum``, ``quantum_probability``,
            ``bias_strength``, ``posterior``.

        Returns
        -------
        dict
            Full risk profile with hard-block authority.
        """
        acc = account_state or {}
        enrich = enrichment or {}

        # ── Extract account state ────────────────────────────────
        equity = float(acc.get("equity", 0.0))
        peak = float(acc.get("peak_equity", equity if equity > 0 else 0.0))
        daily_loss_pct = float(acc.get("daily_loss_pct", 0.0))
        consec_losses = int(acc.get("consecutive_losses", 0))
        vol_cluster = str(acc.get("vol_cluster", "NORMAL"))
        corr_exposure = float(acc.get("corr_exposure", 0.0))
        base_kelly = float(acc.get("base_kelly", 0.25))

        # Compute drawdown from equity/peak when available
        if peak > 0 and equity > 0:
            current_dd = self._compute_drawdown(equity, peak)
        else:
            # Fallback: use passed drawdown_pct (may be 0–100 or 0–1)
            raw_dd = float(acc.get("drawdown_pct", 0.0))
            current_dd = raw_dd / 100.0 if raw_dd > 1.0 else raw_dd

        # Daily DD as fraction
        daily_dd = daily_loss_pct / 100.0 if daily_loss_pct > 1.0 else daily_loss_pct

        warnings: list[str] = []

        # ══════════════════════════════════════════════════════════
        # 1️⃣  DRAWDOWN TIERS
        # ══════════════════════════════════════════════════════════
        drawdown_level, risk_multiplier, risk_status, hard_block = self._classify_drawdown(current_dd)

        if consec_losses >= 3:
            risk_multiplier *= 0.5
            warnings.append(f"CONSECUTIVE_LOSSES_{consec_losses}")
        elif consec_losses >= 2:
            risk_multiplier *= 0.75

        # ══════════════════════════════════════════════════════════
        # 2️⃣  VOLATILITY CLUSTER ADJUSTMENT
        # ══════════════════════════════════════════════════════════
        vol_mult = self._vol_cluster_multiplier(vol_cluster)
        risk_multiplier *= vol_mult

        # GARCH-engine enrichment (optional, from engines/)
        if _vol_cluster_model is not None and trade_returns:
            try:
                vc = _vol_cluster_model.analyze(trade_returns)
                if vc.clustering_detected and vc.risk_multiplier > 1.0:
                    risk_multiplier *= min(vc.risk_multiplier, 1.5)
                    if vc.risk_multiplier > 1.2:
                        warnings.append("VOL_CLUSTERING_DETECTED")
            except Exception as exc:
                logger.debug("[L6] vol-clustering enrichment skipped: %s", exc)

        # ══════════════════════════════════════════════════════════
        # 3️⃣  CORRELATION EXPOSURE DAMPENER
        # ══════════════════════════════════════════════════════════
        corr_mult = self._correlation_multiplier(corr_exposure)
        risk_multiplier *= corr_mult
        if corr_mult < 1.0:
            risk_status = "CORRELATION_STRESS"
            warnings.append(f"CORRELATION_STRESS(exposure={corr_exposure:.2f})")

        # Correlation risk engine enrichment (optional, from engines/)
        if _corr_engine is not None and pair_returns and len(pair_returns) >= 2:
            try:
                import numpy as np  # noqa: PLC0415

                labels = sorted(pair_returns.keys())
                series = [pair_returns[lbl] for lbl in labels]
                min_len = min(len(s) for s in series)

                if min_len >= 20:
                    matrix = np.array(
                        [s[:min_len] for s in series],
                        dtype=np.float64,
                    )
                    cr = _corr_engine.evaluate(matrix, pair_labels=labels)

                    if not cr.passed:
                        risk_multiplier *= 0.6
                        risk_status = "CORRELATION_STRESS"
                        warnings.append("CORR_ENGINE_BLOCK")
            except Exception as exc:
                logger.debug("[L6] correlation-risk enrichment skipped: %s", exc)

        # ══════════════════════════════════════════════════════════
        # 4️⃣  LRCE — FIELD STABILITY
        # ══════════════════════════════════════════════════════════
        lrce = self._compute_lrce(enrich)

        if lrce > self.lrce_block_threshold:
            risk_status = "UNSTABLE_FIELD"
            hard_block = True
            warnings.append(f"LRCE_FRACTURE({lrce:.3f})")

        # ══════════════════════════════════════════════════════════
        # 5️⃣  ROLLING SHARPE DEGRADATION
        # ══════════════════════════════════════════════════════════
        sharpe = self._rolling_sharpe(trade_returns or [])

        if trade_returns and len(trade_returns) >= self.sharpe_lookback:  # noqa: SIM102
            if sharpe < self.sharpe_degradation_threshold:
                risk_multiplier *= 0.6
                if risk_status == "OPTIMAL":
                    risk_status = "SHARPE_DEGRADATION"
                warnings.append(f"SHARPE_DEGRADATION({sharpe:.3f})")

        # ══════════════════════════════════════════════════════════
        # 6️⃣  PROP-FIRM HARD RULES
        # ══════════════════════════════════════════════════════════
        if daily_dd > self._max_daily_dd:
            hard_block = True
            risk_status = "DAILY_LIMIT_BREACH"
            warnings.append(f"DAILY_DD_BREACH({daily_dd:.4f}>{self._max_daily_dd:.4f})")

        if current_dd > self._max_total_dd:
            hard_block = True
            risk_status = "TOTAL_DD_BREACH"
            warnings.append(f"TOTAL_DD_BREACH({current_dd:.4f}>{self._max_total_dd:.4f})")

        # ══════════════════════════════════════════════════════════
        # 7️⃣  KELLY FRACTION DAMPENER
        # ══════════════════════════════════════════════════════════
        adjusted_kelly = self._kelly_dampener(base_kelly, current_dd)

        # ══════════════════════════════════════════════════════════
        # FINAL RISK CALCULATION
        # ══════════════════════════════════════════════════════════
        risk_multiplier = max(0.0, min(1.0, risk_multiplier))
        max_risk_pct = self._base_risk_pct * risk_multiplier

        if hard_block:
            max_risk_pct = 0.0
            adjusted_kelly = 0.0

        # RR advisory flag (non-blocking)
        if rr < 1.5:
            warnings.append(f"LOW_RR_RATIO({rr:.2f})")

        logger.info(
            "[L6] dd=%.4f level=%s status=%s mult=%.4f lrce=%.4f sharpe=%.3f kelly=%.4f risk_ok=%s",
            current_dd,
            drawdown_level,
            risk_status,
            risk_multiplier,
            lrce,
            sharpe,
            adjusted_kelly,
            not hard_block,
        )

        return {
            # Core risk profile (consumed by L10 + L12)
            "risk_status": risk_status,
            "propfirm_compliant": not hard_block,
            "drawdown_level": drawdown_level,
            "risk_multiplier": round(risk_multiplier, 4),
            "lrce": round(lrce, 4),
            "rolling_sharpe": round(sharpe, 4),
            "kelly_adjusted": round(adjusted_kelly, 4),
            "max_risk_pct": round(max_risk_pct, 6),
            "risk_ok": not hard_block,
            "valid": True,
            # Advisory details
            "warnings": warnings,
            "rr_ratio": rr,
            "current_drawdown": round(current_dd, 6),
        }
