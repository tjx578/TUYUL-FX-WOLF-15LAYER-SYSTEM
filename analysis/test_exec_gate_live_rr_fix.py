"""Regression tests proving the execution-gate live-RR / provisional-target fix.

Reproduces the real USDJPY MICROBOOST_COUNTER_ENTRY case that was stuck as a
non-final ``signal_decision_update_json`` (final SignalJSON log stayed empty)
because the live-RR gate recomputed RR from sl_safe while the target ladder was
projected from sl_tight, falsely tripping LIVE_RR_BELOW_MINIMUM.

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

from analysis.signal_execution_gates import evaluate_signal_execution_gates
from analysis.signal_json_gate_adapter import SignalJsonGateAdapter, SignalJsonGateConfig


def _usdjpy_promoted_candidate() -> dict:
    """The promoted final BUY candidate *before* the gate adapter demoted it.

    Mirrors the real log: M15 closed above resistance -> confirmed breakout
    continuation, but only RR-projected provisional targets are available
    (structure ladder not ready), so rr_to_valid_target is unset.
    """
    return {
        "symbol": "USDJPY",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "status": "BUY_BREAKOUT_CONTINUATION_VALID",
        "final_direction": "BUY",
        "candidate_direction": "BUY",
        "valid_for_execution": True,
        "entry_reference_price": 159.639,
        "signal_valid_price": 159.639,
        "entry_zone": [159.639, 159.6475],
        "sl_tight": 159.519,
        "sl_safe": 159.439,
        "tp1": 159.759,
        "tp2": 159.879,
        "tp3": 159.939,
        "tp4": 159.999,
        "tp_min_rr": 159.939,
        "rr_to_tp1_tight": 1.0,
        "rr_to_tp2_tight": 2.0,
        "rr_to_tp3_tight": 2.5,
        "rr_status": "VALID",
        "min_rr_required": 2.5,
        "target_mode": "PROVISIONAL_RR_FALLBACK",
        "target_source": "rr_projection_only",
        "tp_status": "VALID_FROM_TP3",
        "structure_targets_available": False,
        "tradeplan_context_ready": False,
        "targets_execution_usable": True,
        "phase_priced": "RESISTANCE_PRESSURE_WARNING",
        "phase_unpriced": "REPEATED_MICROBOOST",
        "m15_confirmation_status": "M15_CLOSE_ABOVE_RESISTANCE",
        "market_context_applied": True,
        "key_resistance": 159.639,
        "key_support": 159.631,
        # NOTE: deliberately NO rr_to_valid_target / tp_min_rr_value / selected_sl
        # and NO bid/ask -> live_price falls back to entry, exactly as in the log.
    }


def test_confirmed_buy_now_allows_execution():
    """Fix #1 + #2: the stuck USDJPY BUY must pass the gate as ALLOW."""
    decision = evaluate_signal_execution_gates(_usdjpy_promoted_candidate())
    assert decision.applies is True
    assert decision.decision == "ALLOW", decision.reasons
    assert decision.execution_status == "EXECUTION_GATE_ALLOWED"
    # RR is reconstructed on the sl_tight basis -> the true 2.5, not the
    # sl_safe-deflated 1.5 that used to fire LIVE_RR_BELOW_MINIMUM.
    assert decision.live_rr is not None
    assert decision.live_rr["rr"] == 2.5
    assert "LIVE_RR_BELOW_MINIMUM" not in decision.reasons


def test_adapter_does_not_demote_to_decision_update():
    """In ENFORCE mode the confirmed BUY stays a final signal (not demoted)."""
    adapter = SignalJsonGateAdapter(
        SignalJsonGateConfig(enabled=True, enforce=True, final_barrier=True, emit_sidecar=False)
    )
    out = adapter.apply(_usdjpy_promoted_candidate())
    assert out.get("event") != "signal_decision_update_json"
    assert str(out.get("final_direction")).upper() == "BUY"
    assert out.get("valid_for_execution") is True
    assert out.get("direction_validation_status") != "FINAL_CANDIDATE_BLOCKED_BY_EXECUTION_GATE"


def test_genuine_chase_still_blocks():
    """Regression: a real chase far above entry with low live RR must still BLOCK."""
    payload = _usdjpy_promoted_candidate()
    payload.update({"bid": 160.095, "ask": 160.105})  # ~46 pips above entry
    decision = evaluate_signal_execution_gates(payload)
    assert decision.decision == "BLOCK"
    assert (
        "PRICE_CHASE_TOO_FAR_FROM_ENTRY_REFERENCE" in decision.reasons
        or "LIVE_RR_BELOW_MINIMUM" in decision.reasons
    )


def test_low_rr_near_entry_still_blocks():
    """Regression: if even the sl_tight RR is below minimum, the gate still BLOCKs."""
    payload = _usdjpy_promoted_candidate()
    # Pull tp3/target in so RR-to-tight < 2.5 and clear the provisional RR fields.
    payload.update(
        {
            "tp3": 159.689,
            "tp_min_rr": 159.689,
            "rr_to_tp3_tight": 1.0,
            "rr_to_tp2_tight": 0.8,
            "targets_execution_usable": False,
        }
    )
    decision = evaluate_signal_execution_gates(payload)
    assert decision.decision in {"BLOCK", "DEFER"}
    assert decision.decision != "ALLOW"


def test_deferred_retest_becomes_conditional_final_when_enabled():
    """Fix #3 (opt-in): a directionally-valid DEFER -> CONDITIONAL final WAIT_RETEST."""
    payload = _usdjpy_promoted_candidate()
    payload["status"] = "BUY_BREAKOUT_RETEST_VALID"  # contains RETEST -> retest gate defers
    # default flag OFF -> demoted to non-final decision update
    off = SignalJsonGateAdapter(
        SignalJsonGateConfig(enabled=True, enforce=True, final_barrier=True, emit_sidecar=False)
    ).apply(dict(payload))
    assert off.get("event") == "signal_decision_update_json"
    assert off.get("is_final_signal") is False

    # flag ON -> stays final, annotated WAIT_RETEST pending limit
    on = SignalJsonGateAdapter(
        SignalJsonGateConfig(
            enabled=True,
            enforce=True,
            final_barrier=True,
            emit_sidecar=False,
            emit_deferred_as_conditional_final=True,
        )
    ).apply(dict(payload))
    assert on.get("event") != "signal_decision_update_json"
    assert on.get("is_final_signal") is True
    assert on.get("execution_mode") == "WAIT_RETEST"
    assert on.get("entry_type") == "PENDING_LIMIT"
    assert str(on.get("final_direction")).upper() == "BUY"


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
