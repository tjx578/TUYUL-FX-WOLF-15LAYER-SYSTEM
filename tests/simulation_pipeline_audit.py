"""
Pipeline Audit Simulation — Trace data flow from hulu (L1) ke hilir (L12/L13/L14/L15).

Simulates 6 scenarios:
  1. COLD_START:     No trade history, no account state — fresh system
  2. WARM_HEALTHY:   All layers produce valid data — should reach EXECUTE
  3. NO_L7_DATA:     L7 Monte Carlo receives empty returns → gate 5 fails
  4. DEGRADED_L2:    L2 fusion fails → conf12=0 → gate 9 fails
  5. NO_L8_DATA:     L8 TII produces 0.0 → gates 1+2 fail
  6. L11_ATR_WARMUP: L11 cannot compute SL/TP → gate 3 fails (rr=0)

For each scenario, builds a synthesis dict and runs generate_l12_verdict()
to prove which gates block EXECUTE and which data gaps cause it.
"""

from __future__ import annotations

import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constitution.verdict_engine import generate_l12_verdict
from pipeline.phases.synthesis import build_l12_synthesis


def make_layer_results(
    *,
    # L1
    regime: str = "TREND",
    volatility_level: str = "NORMAL",
    regime_confidence: float = 0.8,
    # L2
    reflex_coherence: float = 0.75,
    conf12: float | None = None,
    frpc_state: str = "SYNC",
    frpc_energy: float = 0.85,
    # L3
    trend: str = "BULLISH",
    atr: float = 0.0015,
    atr_mean_20: float = 0.0012,
    trq3d_energy: float = 0.7,
    # L4
    technical_score: int = 80,
    wolf_30_total: int = 24,
    f_score: int = 5,
    t_score: int = 10,
    fta_score: float = 0.72,
    exec_score: int = 4,
    # L5
    psychology_score: int = 75,
    eaf_score: float = 0.6,
    current_drawdown: float = 0.8,
    # L6
    propfirm_compliant: bool = True,
    risk_status: str = "ACCEPTABLE",
    drawdown_level: str = "LEVEL_0",
    lrce: float = 0.0,
    # L7
    win_probability: float = 65.0,
    profit_factor: float = 1.8,
    risk_of_ruin: float = 0.05,
    bayesian_posterior: float = 0.62,
    bayesian_ci_low: float = 0.50,
    bayesian_ci_high: float = 0.74,
    mc_passed: bool = True,
    # L8
    tii_sym: float = 0.85,
    integrity: float = 0.92,
    twms_score: float = 0.78,
    # L9
    dvg_confidence: float = 0.6,
    liquidity_score: float = 0.7,
    smart_money_signal: str = "BUY",
    # L10
    lot_size: float = 0.10,
    risk_pct: float = 1.0,
    fta_score_l10: float | None = None,
    position_ok: bool = True,
    # L11
    entry_price: float = 1.08500,
    stop_loss: float = 1.08200,
    take_profit: float = 1.09100,
    rr_ratio: float = 2.0,
) -> dict:
    """Construct a layer_results dict simulating all 12 layer outputs."""
    result: dict = {
        "L1": {
            "regime": regime,
            "volatility_level": volatility_level,
            "regime_confidence": regime_confidence,
            "valid": True,
            "dominant_force": "TREND",
            "csi": 0.7,
        },
        "L2": {
            "reflex_coherence": reflex_coherence,
            "frpc_state": frpc_state,
            "frpc_energy": frpc_energy,
        },
        "L3": {
            "trend": trend,
            "atr": atr,
            "atr_mean_20": atr_mean_20,
            "trq3d_energy": trq3d_energy,
            "drift": 0.001,
        },
        "L4": {
            "technical_score": technical_score,
            "wolf_30_point": {
                "total": wolf_30_total,
                "f_score": f_score,
                "t_score": t_score,
                "fta_score": fta_score,
                "exec_score": exec_score,
            },
        },
        "L5": {
            "psychology_score": psychology_score,
            "eaf_score": eaf_score,
            "current_drawdown": current_drawdown,
        },
        "L6": {
            "propfirm_compliant": propfirm_compliant,
            "risk_status": risk_status,
            "drawdown_level": drawdown_level,
            "current_drawdown": current_drawdown,
            "lrce": lrce,
            "risk_multiplier": 1.0,
            "rolling_sharpe": 0.8,
            "kelly_adjusted": 0.15,
        },
        "L7": {
            "win_probability": win_probability,
            "profit_factor": profit_factor,
            "risk_of_ruin": risk_of_ruin,
            "bayesian_posterior": bayesian_posterior,
            "bayesian_ci_low": bayesian_ci_low,
            "bayesian_ci_high": bayesian_ci_high,
            "mc_passed_threshold": mc_passed,
            "validation": "PASS" if mc_passed else "FAIL",
            "conf12_raw": 0.65,
        },
        "L8": {
            "tii_sym": tii_sym,
            "integrity": integrity,
            "twms_score": twms_score,
        },
        "L9": {
            "dvg_confidence": dvg_confidence,
            "liquidity_score": liquidity_score,
            "smart_money_signal": smart_money_signal,
            "ob_present": True,
            "fvg_present": False,
        },
        "L10": {
            "lot_size": lot_size,
            "adjusted_risk_pct": risk_pct,
            "fta_score": fta_score_l10 if fta_score_l10 is not None else fta_score,
            "fta_multiplier": 1.0,
            "position_ok": position_ok,
            "risk_amount": 100.0,
        },
        "L11": {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit_1": take_profit,
            "rr": rr_ratio,
            "battle_strategy": "SHADOW_STRIKE",
            "entry_zone": f"{entry_price - 0.001:.5f}-{entry_price:.5f}",
        },
    }
    if conf12 is not None:
        result["L2"]["conf12"] = conf12
    return result


SCENARIOS = {
    "1_COLD_START": {
        "desc": "Fresh system — no trade history, all layers produce defaults/zeros",
        "overrides": {
            "regime_confidence": 0.0,
            "reflex_coherence": 0.0,
            "conf12": None,  # Will derive from (tii+integrity)/2 = 0.0
            "frpc_state": "DESYNC",
            "frpc_energy": 0.0,
            "trend": "NEUTRAL",
            "atr": 0.0,
            "atr_mean_20": 0.0,
            "trq3d_energy": 0.0,
            "technical_score": 0,
            "wolf_30_total": 0,
            "f_score": 0,
            "t_score": 0,
            "fta_score": 0.0,
            "exec_score": 0,
            "psychology_score": 0,
            "eaf_score": 0.0,
            "current_drawdown": 0.0,
            "win_probability": 0.0,
            "profit_factor": 0.0,
            "risk_of_ruin": 1.0,
            "bayesian_posterior": 0.0,
            "bayesian_ci_low": 0.0,
            "bayesian_ci_high": 0.0,
            "mc_passed": False,
            "tii_sym": 0.0,
            "integrity": 0.0,
            "twms_score": 0.0,
            "dvg_confidence": 0.0,
            "liquidity_score": 0.0,
            "smart_money_signal": "NEUTRAL",
            "lot_size": 0.01,
            "fta_score_l10": 0.0,
            "position_ok": False,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "rr_ratio": 0.0,
        },
    },
    "2_WARM_HEALTHY": {
        "desc": "Warm system — all layers healthy, should produce EXECUTE",
        "overrides": {
            "conf12": 0.78,
            "tii_sym": 0.85,
            "integrity": 0.92,
            "win_probability": 65.0,
            "rr_ratio": 2.5,
            "fta_score": 0.72,
        },
    },
    "3_NO_L7_DATA": {
        "desc": "L7 has no trade returns — win_prob=0, risk_of_ruin=1.0",
        "overrides": {
            "conf12": 0.75,
            "tii_sym": 0.80,
            "integrity": 0.88,
            "win_probability": 0.0,
            "profit_factor": 0.0,
            "risk_of_ruin": 1.0,
            "bayesian_posterior": 0.0,
            "mc_passed": False,
            "rr_ratio": 2.0,
            "fta_score": 0.65,
        },
    },
    "4_DEGRADED_L2": {
        "desc": "L2 fusion fails — conf12 falls to (tii+integrity)/2",
        "overrides": {
            "conf12": None,  # Will derive: (0.80+0.88)/2 = 0.84 -- PASS
            "tii_sym": 0.80,
            "integrity": 0.88,
            "win_probability": 60.0,
            "rr_ratio": 2.0,
            "fta_score": 0.65,
            "frpc_state": "DESYNC",
            "frpc_energy": 0.0,
        },
    },
    "4b_DEGRADED_L2_LOW_TII": {
        "desc": "L2 fusion fails with low TII — conf12 derived too low",
        "overrides": {
            "conf12": None,
            "tii_sym": 0.50,
            "integrity": 0.55,
            "win_probability": 55.0,
            "rr_ratio": 2.0,
            "fta_score": 0.60,
            "frpc_state": "DESYNC",
            "frpc_energy": 0.0,
        },
    },
    "5_NO_L8_DATA": {
        "desc": "L8 missing — TII=0.0, integrity=0.0 → gates 1+2 fail",
        "overrides": {
            "conf12": 0.70,
            "tii_sym": 0.0,
            "integrity": 0.0,
            "twms_score": 0.0,
            "win_probability": 62.0,
            "rr_ratio": 2.0,
            "fta_score": 0.65,
        },
    },
    "6_L11_ATR_WARMUP": {
        "desc": "L11 ATR insufficient — SL/TP/RR all zero → gate 3 fails",
        "overrides": {
            "conf12": 0.75,
            "tii_sym": 0.80,
            "integrity": 0.85,
            "win_probability": 58.0,
            "rr_ratio": 0.0,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "fta_score": 0.65,
        },
    },
}


def gate_emoji(status: str) -> str:
    return "PASS" if status == "PASS" else "FAIL"


def run_scenario(name: str, desc: str, overrides: dict) -> dict:
    """Run one scenario through synthesis + verdict pipeline."""
    layer_results = make_layer_results(**overrides)
    synthesis = build_l12_synthesis(layer_results, symbol="EURUSD")
    verdict_result = generate_l12_verdict(synthesis, governance_penalty=0.0)
    return {
        "scenario": name,
        "description": desc,
        "verdict": verdict_result.get("verdict", "UNKNOWN"),
        "confidence": verdict_result.get("confidence", "UNKNOWN"),
        "proceed_to_L13": verdict_result.get("proceed_to_L13", False),
        "proceed_pipeline": (
            verdict_result.get("proceed_to_L13", False) or verdict_result.get("verdict", "").startswith("EXECUTE")
        ),
        "gates": {k: v for k, v in verdict_result.get("gates", {}).items() if k.startswith("gate_")},
        "gates_passed": verdict_result.get("gates", {}).get("passed", 0),
        "gates_total": verdict_result.get("gates", {}).get("total", 0),
        "direction": verdict_result.get("direction", ""),
        # Key synthesis values for debugging
        "synthesis_debug": {
            "conf12": synthesis.get("layers", {}).get("conf12", "N/A"),
            "L7_monte_carlo_win": synthesis.get("layers", {}).get("L7_monte_carlo_win", "N/A"),
            "L8_tii_sym": synthesis.get("layers", {}).get("L8_tii_sym", "N/A"),
            "L8_integrity_index": synthesis.get("layers", {}).get("L8_integrity_index", "N/A"),
            "rr_ratio": synthesis.get("execution", {}).get("rr_ratio", "N/A"),
            "fta_score": synthesis.get("scores", {}).get("fta_score", "N/A"),
            "propfirm_compliant": synthesis.get("propfirm", {}).get("compliant", "N/A"),
            "current_drawdown": synthesis.get("risk", {}).get("current_drawdown", "N/A"),
            "direction": synthesis.get("execution", {}).get("direction", "N/A"),
            "wolf_30_point": synthesis.get("scores", {}).get("wolf_30_point", "N/A"),
        },
    }


def main() -> None:
    print("=" * 80)
    print("  WOLF-15 PIPELINE AUDIT SIMULATION")
    print("  Tracing data flow hulu->hilir through synthesis + L12 verdict")
    print("=" * 80)

    results = []
    for name, cfg in SCENARIOS.items():
        r = run_scenario(name, cfg["desc"], cfg["overrides"])
        results.append(r)

    for r in results:
        print(f"\n{'─' * 80}")
        print(f"  SCENARIO: {r['scenario']}")
        print(f"  {r['description']}")
        print(f"{'─' * 80}")
        print(f"  VERDICT:       {r['verdict']}")
        print(f"  CONFIDENCE:    {r['confidence']}")
        print(f"  DIRECTION:     {r['direction']}")
        print(f"  PROCEED→L13 (field):  {r['proceed_to_L13']}")
        print(f"  PROCEED→L13 (pipe):   {r['proceed_pipeline']}")
        print(f"  GATES:         {r['gates_passed']}/{r['gates_total']}")
        print()
        for gname, gval in r["gates"].items():
            status = gate_emoji(gval)
            print(f"    {gname:30s} {status}")
        print()
        print("  SYNTHESIS DEBUG:")
        for k, v in r["synthesis_debug"].items():
            val = f"{v:.4f}" if isinstance(v, float) else str(v)
            print(f"    {k:30s} = {val}")

    # Summary table
    print(f"\n{'=' * 80}")
    print("  SUMMARY — WHO REACHES L12/L13?")
    print(f"{'=' * 80}")
    for r in results:
        status = "→ L13/L14/L15" if r["proceed_pipeline"] else "✗ BLOCKED at L12"
        fail_gates = [gn.replace("gate_", "G") for gn, gv in r["gates"].items() if gv == "FAIL"]
        fail_str = ", ".join(fail_gates) if fail_gates else "NONE"
        print(f"  {r['scenario']:30s}  {r['verdict']:30s}  {status}  [FAIL: {fail_str}]")

    # Verdict distribution
    verdicts = [r["verdict"] for r in results]
    executes = sum(1 for v in verdicts if v.startswith("EXECUTE"))
    holds = sum(1 for v in verdicts if v == "HOLD")
    no_trades = sum(1 for v in verdicts if v == "NO_TRADE")
    print(f"\n  Distribution: {executes} EXECUTE | {holds} HOLD | {no_trades} NO_TRADE")
    print(f"  L13+ reached (field): {sum(1 for r in results if r['proceed_to_L13'])}/{len(results)}")
    print(f"  L13+ reached (pipe):  {sum(1 for r in results if r['proceed_pipeline'])}/{len(results)}")


if __name__ == "__main__":
    main()
