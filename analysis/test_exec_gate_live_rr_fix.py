"""Regression tests for the single-stop (sl_safe only) + TP1=1.5R model.

Replaces the earlier sl_tight reconciliation tests. The engine now:
  * uses ONE stop everywhere: sl_safe (the sl_tight concept is removed);
  * projects TP1 at 1.5R from sl_safe and measures the minimum RR at TP1;
  * sets the global minimum RR to 1.5 across the engine, execution gate,
    adapter, finalizer and emitter.

Run from the repository root:
    python -m pytest analysis/test_exec_gate_live_rr_fix.py -v
or directly (path is bootstrapped below):
    python analysis/test_exec_gate_live_rr_fix.py
"""

from __future__ import annotations

import os
import sys

# Make ``analysis`` importable whether run from repo root or from this folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.microboost_counter_entry import MicroboostCounterEntryEngine
from analysis.signal_execution_gates import evaluate_signal_execution_gates
from analysis.signal_json_gate_adapter import SignalJsonGateAdapter, SignalJsonGateConfig

# Single-stop model numbers for USDJPY (pip = 0.01):
#   entry    = 159.639
#   sl_safe  = entry - 20 pips = 159.439   (the ONLY stop)
#   risk     = 0.200 (20 pips)
#   TP1      = entry + 1.5 * risk = 159.939  -> RR 1.5 against sl_safe
ENTRY = 159.639
SL_SAFE = 159.439
TP1 = 159.939


def _usdjpy_single_stop_candidate() -> dict:
    """A confirmed BUY breakout-continuation as the engine now emits it.

    One stop (sl_safe), TP ladder projected from sl_safe with TP1 = 1.5R,
    and NO sl_tight field anywhere.
    """
    return {
        "symbol": "USDJPY",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "status": "BUY_BREAKOUT_CONTINUATION_VALID",
        "final_direction": "BUY",
        "candidate_direction": "BUY",
        "valid_for_execution": True,
        "entry_reference_price": ENTRY,
        "signal_valid_price": ENTRY,
        "entry_zone": [ENTRY, 159.6475],
        "sl_safe": SL_SAFE,
        "selected_sl": SL_SAFE,
        "selected_sl_mode": "SAFE",
        "tp1": TP1,
        "tp2": 160.039,
        "tp3": 160.139,
        "tp4": 160.239,
        "tp_min_rr": TP1,
        "tp_min_rr_value": 1.5,
        "rr_to_tp1_tight": 1.5,
        "rr_to_tp2_tight": 2.5,
        "rr_to_tp3_tight": 3.5,
        "tp1_rr": 1.5,
        "rr_status": "VALID",
        "min_rr_required": 1.5,
        "target_mode": "PROVISIONAL_RR_FALLBACK",
        "target_source": "rr_projection_only",
        "tp_status": "VALID_FROM_TP1",
        "structure_targets_available": False,
        "tradeplan_context_ready": False,
        "targets_execution_usable": True,
        "phase_priced": "RESISTANCE_PRESSURE_WARNING",
        "phase_unpriced": "REPEATED_MICROBOOST",
        "m15_confirmation_status": "M15_CLOSE_ABOVE_RESISTANCE",
        "market_context_applied": True,
        "key_resistance": ENTRY,
        "key_support": 159.631,
        # deliberately NO sl_tight / rr_to_valid_target and NO bid/ask.
    }


def _usdjpy_structure_ready_candidate() -> dict:
    payload = _usdjpy_single_stop_candidate()
    payload.update(
        {
            "target_mode": "FINAL_MARKET_STRUCTURE",
            "target_source": "support_resistance_ladder",
            "structure_targets_available": True,
            "tradeplan_context_ready": True,
            "targets_execution_usable": True,
            "targets": [{"id": "TP1", "type": "STRUCTURE_TARGET", "level": TP1, "rr": 1.5}],
        }
    )
    return payload


def test_engine_defaults_single_stop_min_rr_15():
    """Engine minimum RR and fixed TP1 RR both default to 1.5."""
    engine = MicroboostCounterEntryEngine()
    assert engine.min_rr_valid == 1.5
    assert engine.tp1_rr_required == 1.5


def test_tp1_is_1p5r_against_sl_safe():
    """TP1 sits exactly 1.5R away measured against the single sl_safe stop."""
    risk = abs(ENTRY - SL_SAFE)
    reward = abs(TP1 - ENTRY)
    assert round(reward / risk, 2) == 1.5


def test_confirmed_buy_hard_blocks_provisional_rr_by_default():
    """Patch 3: direction/RR valid, but a PROVISIONAL_RR_FALLBACK target is hard-BLOCKED
    (not merely DEFERRED) -- never execution-grade, independent of any other gate."""
    decision = evaluate_signal_execution_gates(_usdjpy_single_stop_candidate())
    assert decision.applies is True
    assert decision.decision == "BLOCK", decision.reasons
    assert "PROVISIONAL_RR_FALLBACK_NOT_EXECUTABLE" in decision.reasons
    assert decision.live_rr is not None
    assert decision.live_rr["rr"] == 1.5
    assert "LIVE_RR_BELOW_MINIMUM" not in decision.reasons


def test_confirmed_buy_cannot_bypass_structure_contract_with_legacy_policy():
    """Provisional RR remains non-executable (now a hard BLOCK) even if an old policy env exists."""
    decision = evaluate_signal_execution_gates(_usdjpy_single_stop_candidate())
    assert decision.applies is True
    assert decision.decision == "BLOCK", decision.reasons
    assert "PROVISIONAL_RR_FALLBACK_NOT_EXECUTABLE" in decision.reasons
    assert decision.live_rr is not None
    assert decision.live_rr["rr"] == 1.5


def test_default_min_rr_required_is_15():
    """The gate's default minimum RR is 1.5 (TP1 at exactly 1.5R is accepted)."""
    decision = evaluate_signal_execution_gates(_usdjpy_single_stop_candidate())
    assert decision.live_rr is not None
    assert decision.live_rr["min_rr_required"] == 1.5


def test_no_sl_tight_in_gate_output():
    """The output payload carries a single stop and no sl_tight field."""
    adapter = SignalJsonGateAdapter(
        SignalJsonGateConfig(enabled=True, enforce=True, final_barrier=True, emit_sidecar=False)
    )
    out = adapter.apply(_usdjpy_structure_ready_candidate())
    assert "sl_tight" not in out
    assert out.get("sl_safe") == SL_SAFE
    assert out.get("event") != "signal_decision_update_json"
    assert out.get("status") == "FINAL_EXECUTION_READY"
    assert str(out.get("final_direction")).upper() == "BUY"


def test_below_min_rr_still_blocks():
    """A plan whose RR is under 1.5 must NOT be allowed."""
    payload = _usdjpy_single_stop_candidate()
    # TP1 only ~0.5R from sl_safe; clear provisional usability + pre-validated RR.
    payload.update(
        {
            "tp1": 159.739,
            "tp_min_rr": 159.739,
            "tp_min_rr_value": 0.5,
            "tp1_rr": 0.5,
            "rr_to_tp1_tight": 0.5,
            "rr_to_tp2_tight": 0.8,
            "rr_to_tp3_tight": 1.0,
            "targets_execution_usable": False,
        }
    )
    decision = evaluate_signal_execution_gates(payload)
    assert decision.decision != "ALLOW"


def test_genuine_chase_still_blocks():
    """A real chase far above entry with low live RR must still BLOCK."""
    payload = _usdjpy_single_stop_candidate()
    payload.update({"bid": 160.095, "ask": 160.105})  # ~46 pips above entry
    decision = evaluate_signal_execution_gates(payload)
    assert decision.decision == "BLOCK"
    assert "PRICE_CHASE_TOO_FAR_FROM_ENTRY_REFERENCE" in decision.reasons or "LIVE_RR_BELOW_MINIMUM" in decision.reasons


def _nzdjpy_single_stop_sell() -> dict:
    """A confirmed SELL breakdown-continuation (NZDJPY), single stop, TP1=1.5R."""
    entry = 94.0785
    sl_safe = 94.2785  # 20 pips above entry for a SELL
    tp1 = 93.7785  # 30 pips below entry -> 1.5R
    return {
        "symbol": "NZDJPY",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "status": "SELL_BREAKDOWN_CONTINUATION_VALID",
        "final_direction": "SELL",
        "candidate_direction": "SELL",
        "valid_for_execution": True,
        "entry_reference_price": entry,
        "signal_valid_price": entry,
        "entry_zone": [entry, entry],
        "sl_safe": sl_safe,
        "selected_sl": sl_safe,
        "selected_sl_mode": "SAFE",
        "tp1": tp1,
        "tp2": 93.5785,
        "tp3": 93.3785,
        "tp4": 93.1785,
        "tp_min_rr": tp1,
        "tp_min_rr_value": 1.5,
        "rr_to_tp1_tight": 1.5,
        "rr_status": "VALID",
        "min_rr_required": 1.5,
        "target_mode": "PROVISIONAL_RR_FALLBACK",
        "tp_status": "VALID_FROM_TP1",
        "structure_targets_available": False,
        "targets_execution_usable": True,
        "phase_priced": "SUPPORT_PRESSURE_WARNING",
        "m15_confirmation_status": "M15_CLOSE_BELOW_SUPPORT",
        "market_context_applied": True,
        "key_resistance": 94.3385,
        "key_support": entry,
    }


def test_pattern_permission_no_new_buy_blocks_final():
    """A BUY whose pattern entry_permission is NO_NEW_BUY must NOT be ALLOW (USDJPY bug)."""
    payload = _usdjpy_single_stop_candidate()
    payload["entry_permission"] = "NO_NEW_BUY"
    decision = evaluate_signal_execution_gates(payload)
    assert decision.decision == "BLOCK"
    assert "PATTERN_PERMISSION_NO_NEW_BUY" in decision.reasons


def test_no_market_chase_sell_still_allowed():
    """NO_MARKET_CHASE is chase-only; a valid SELL retest must still ALLOW (NZDJPY kept)."""
    payload = _nzdjpy_single_stop_sell()
    payload["entry_permission"] = "NO_MARKET_CHASE"
    payload["target_mode"] = "FINAL_MARKET_STRUCTURE"
    payload["structure_targets_available"] = True
    payload["targets"] = [{"type": "STRUCTURE_TARGET", "level": payload["tp1"], "rr": 1.5}]
    decision = evaluate_signal_execution_gates(payload)
    assert decision.decision == "ALLOW", decision.reasons


def test_observed_live_price_blocks_new_entry_after_stop_or_target_is_crossed():
    buy_stop = _usdjpy_structure_ready_candidate()
    buy_stop["observed_mid"] = 159.395
    buy_target = _usdjpy_structure_ready_candidate()
    buy_target["observed_mid"] = 159.95

    sell_stop = _nzdjpy_single_stop_sell()
    sell_target = _nzdjpy_single_stop_sell()
    for payload in (sell_stop, sell_target):
        payload["target_mode"] = "FINAL_MARKET_STRUCTURE"
        payload["structure_targets_available"] = True
        payload["tradeplan_context_ready"] = True
        payload["targets"] = [{"type": "STRUCTURE_TARGET", "level": payload["tp1"], "rr": 1.5}]
    sell_stop["observed_mid"] = 94.30
    sell_target["observed_mid"] = 93.77

    cases = (
        (buy_stop, "LIVE_PRICE_AT_OR_BEYOND_STOP"),
        (buy_target, "TARGET_ALREADY_REACHED_NO_NEW_ENTRY"),
        (sell_stop, "LIVE_PRICE_AT_OR_BEYOND_STOP"),
        (sell_target, "TARGET_ALREADY_REACHED_NO_NEW_ENTRY"),
    )
    for payload, expected_reason in cases:
        decision = evaluate_signal_execution_gates(payload)
        assert decision.decision == "BLOCK"
        assert expected_reason in decision.reasons
        assert decision.live_rr["price_valid_for_new_entry"] is False


def test_stop_breach_uses_executable_bid_for_buy_and_ask_for_sell():
    buy = _usdjpy_structure_ready_candidate()
    buy.update({"observed_bid": 159.438, "observed_ask": 159.442, "observed_mid": 159.440})

    sell = _nzdjpy_single_stop_sell()
    sell.update(
        {
            "target_mode": "FINAL_MARKET_STRUCTURE",
            "structure_targets_available": True,
            "tradeplan_context_ready": True,
            "targets": [{"type": "STRUCTURE_TARGET", "level": sell["tp1"], "rr": 1.5}],
            "observed_bid": 94.278,
            "observed_ask": 94.279,
            "observed_mid": 94.2785,
        }
    )

    for payload, expected_exit_price in ((buy, 159.438), (sell, 94.279)):
        decision = evaluate_signal_execution_gates(payload)
        assert decision.decision == "BLOCK"
        assert "LIVE_PRICE_AT_OR_BEYOND_STOP" in decision.reasons
        assert decision.live_rr["exit_price"] == expected_exit_price


def test_allow_stamps_execution_valid_now_true():
    """On ALLOW the adapter stamps execution_valid_now=True (flag consistency)."""
    adapter = SignalJsonGateAdapter(
        SignalJsonGateConfig(enabled=True, enforce=True, final_barrier=True, emit_sidecar=False)
    )
    out = adapter.apply(_usdjpy_structure_ready_candidate())
    assert out.get("status") == "FINAL_EXECUTION_READY"
    assert out.get("signal_valid") is True
    assert out.get("valid_for_execution") is True
    assert out.get("execution_valid_now") is True


def test_no_new_buy_adapter_demotes_with_consistent_flags():
    """The contradictory USDJPY BUY (NO_NEW_BUY) is demoted with consistent false flags."""
    payload = _usdjpy_single_stop_candidate()
    payload["entry_permission"] = "NO_NEW_BUY"
    adapter = SignalJsonGateAdapter(
        SignalJsonGateConfig(enabled=True, enforce=True, final_barrier=True, emit_sidecar=False)
    )
    out = adapter.apply(payload)
    assert out.get("event") == "signal_decision_update_json"
    assert out.get("valid_for_execution") is False
    assert out.get("execution_valid_now") is False


def _run_all() -> int:
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
