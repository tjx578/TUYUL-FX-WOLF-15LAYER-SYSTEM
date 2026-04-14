"""
Stage Gates — metric thresholds that must be met before a stage passport is issued.

Each gate evaluates raw metrics against configurable thresholds and returns
a PassportStatus.  Gates are pure functions with no side-effects.

Authority: Governance zone.  Does NOT override L12.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from governance.passport import PassportStatus, Stage, StageMetrics


@dataclass(frozen=True)
class GateThresholds:
    """Per-stage metric thresholds.  Values <= 0 are skipped (disabled)."""

    min_sharpe: float = 0.0
    max_drawdown_pct: float = 100.0
    min_profit_factor: float = 0.0
    min_win_rate: float = 0.0
    min_sample_trades: int = 0
    max_oos_degradation_pct: float = 100.0
    min_stability_score: float = 0.0


# ── Default thresholds per stage (from PAE blueprint) ────────────────────────

BACKTEST_THRESHOLDS = GateThresholds(
    min_sharpe=1.2,
    max_drawdown_pct=8.0,
    min_profit_factor=1.6,
    min_win_rate=0.52,
    min_sample_trades=200,
)

OPTIMIZATION_THRESHOLDS = GateThresholds(
    max_oos_degradation_pct=25.0,
    min_stability_score=0.70,
)

PAPER_THRESHOLDS = GateThresholds(
    min_sharpe=0.0,  # compared via ratio to backtest sharpe externally
    min_sample_trades=40,
    min_win_rate=0.45,
)

ROLLOUT_THRESHOLDS = GateThresholds(
    min_win_rate=0.45,
    max_drawdown_pct=12.0,
)

DEFAULT_THRESHOLDS: dict[Stage, GateThresholds] = {
    Stage.BACKTEST: BACKTEST_THRESHOLDS,
    Stage.OPTIMIZATION: OPTIMIZATION_THRESHOLDS,
    Stage.PAPER: PAPER_THRESHOLDS,
    Stage.ROLLOUT: ROLLOUT_THRESHOLDS,
}


def evaluate_gate(
    stage: Stage,
    metrics: StageMetrics,
    thresholds: GateThresholds | None = None,
) -> tuple[PassportStatus, list[str]]:
    """
    Evaluate metrics against gate thresholds.

    Returns (status, list_of_failure_reasons).
    Empty failure list means PASS.
    """
    t = thresholds or DEFAULT_THRESHOLDS.get(stage, GateThresholds())
    failures: list[str] = []

    if t.min_sharpe > 0 and metrics.sharpe < t.min_sharpe:
        failures.append(f"sharpe {metrics.sharpe:.3f} < {t.min_sharpe}")

    if metrics.max_drawdown_pct > t.max_drawdown_pct:
        failures.append(f"max_dd {metrics.max_drawdown_pct:.2f}% > {t.max_drawdown_pct}%")

    if t.min_profit_factor > 0 and metrics.profit_factor < t.min_profit_factor:
        failures.append(f"pf {metrics.profit_factor:.3f} < {t.min_profit_factor}")

    if t.min_win_rate > 0 and metrics.win_rate < t.min_win_rate:
        failures.append(f"win_rate {metrics.win_rate:.3f} < {t.min_win_rate}")

    if t.min_sample_trades > 0 and metrics.sample_trades < t.min_sample_trades:
        failures.append(f"sample_trades {metrics.sample_trades} < {t.min_sample_trades}")

    if metrics.oos_degradation_pct > t.max_oos_degradation_pct:
        failures.append(f"oos_degradation {metrics.oos_degradation_pct:.2f}% > {t.max_oos_degradation_pct}%")

    if t.min_stability_score > 0 and metrics.stability_score < t.min_stability_score:
        failures.append(f"stability {metrics.stability_score:.3f} < {t.min_stability_score}")

    status = PassportStatus.PASS if not failures else PassportStatus.FAIL
    return status, failures


def evaluate_all_gates(
    passports: dict[Stage, dict[str, Any]],
) -> tuple[bool, dict[Stage, tuple[PassportStatus, list[str]]]]:
    """
    Check whether all required stages have PASS status.

    Parameters
    ----------
    passports : {Stage: {"status": str, ...}}

    Returns (all_passed, per_stage_results).
    """
    results: dict[Stage, tuple[PassportStatus, list[str]]] = {}
    all_passed = True

    for stage in (Stage.BACKTEST, Stage.OPTIMIZATION, Stage.PAPER, Stage.ROLLOUT):
        pp = passports.get(stage)
        if pp is None:
            results[stage] = (PassportStatus.PENDING, ["no passport issued"])
            all_passed = False
        elif pp.get("status") != PassportStatus.PASS.value:
            results[stage] = (
                PassportStatus(pp.get("status", "FAIL")),
                [pp.get("notes", "not passed")],
            )
            all_passed = False
        else:
            results[stage] = (PassportStatus.PASS, [])

    return all_passed, results
