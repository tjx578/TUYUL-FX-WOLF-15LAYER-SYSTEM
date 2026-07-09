from __future__ import annotations

from analysis.microboost_followthrough_role import build_microboost_followthrough_role


def test_microboost_role_marks_buy_pressure_at_resistance_as_absorption_no_chase():
    payload = build_microboost_followthrough_role(
        {
            "symbol": "USDCAD",
            "direction": "BUY",
            "phase_unpriced": "DENSE_MICROBOOST",
            "phase_priced": "EXHAUSTION_AT_RESISTANCE",
            "action": "NO_NEW_BUY_WAIT_SELL_OR_PULLBACK_CONFIRMATION",
            "requires_market_context": False,
            "market_context_snapshot": {
                "pip_value": 0.0001,
                "price_at_signal_start": 1.3600,
                "price_at_signal_end": 1.3668,
                "main_resistance": 1.3670,
                "key_resistance": 1.3670,
                "main_support": 1.3520,
            },
        }
    )

    assert payload["microboost_role"] == "ABSORPTION_WARNING"
    assert payload["microboost_followthrough_bias"] == "NO_CHASE"
    assert payload["microboost_room_to_move_pips"] == 2.0
    assert payload["microboost_pre_move_pips"] == 68.0
    assert payload["microboost_expected_horizon"] == "15M"
    assert payload["microboost_outcome_tracking_required"] is True
    assert payload["microboost_role_valid_for_execution"] is False
    assert payload["valid_for_execution"] is False
    assert payload["is_final_signal"] is False


def test_microboost_role_keeps_unpriced_ignition_context_required():
    payload = build_microboost_followthrough_role(
        {
            "symbol": "EURJPY",
            "direction": "BUY",
            "phase_unpriced": "IGNITION_MICROBOOST",
            "phase_priced": None,
            "action": "VALIDATE_PRICE_THEME_STRUCTURE",
            "requires_market_context": True,
            "market_context_snapshot": None,
        }
    )

    assert payload["microboost_role"] == "IGNITION"
    assert payload["microboost_followthrough_bias"] == "CONTEXT_REQUIRED"
    assert payload["microboost_room_to_move_pips"] is None
    assert payload["microboost_expected_horizon"] == "CONTEXT_REQUIRED"
    assert "MARKET_CONTEXT_REQUIRED" in payload["microboost_role_reason_codes"]
    assert payload["microboost_role_execution_impact"] is False
