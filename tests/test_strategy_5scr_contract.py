from __future__ import annotations

from copy import deepcopy

from contracts.strategy_5scr import evaluate_strategy_5scr_proof


def _signal(*, symbol: str = "CHFJPY", direction: str = "SELL") -> dict:
    entry = 190.0 if direction == "SELL" else 0.55
    stop = 190.5 if direction == "SELL" else 0.545
    target = 189.065 if direction == "SELL" else 0.56515
    lifecycle = f"{symbol}-campaign-001"
    confirmed_at = "2026-07-19T10:15:00+00:00"
    proof = {
        "strategy_model": "STRATEGY_5S_CR_FINAL",
        "rule_version": "5scr.final.2026-07-19",
        "rule_status": "FROZEN",
        "validation_status": "STRONG_PROVISIONAL",
        "out_of_sample_status": "NOT_YET_VALIDATED",
        "production_proven": False,
        "confirmation_policy": "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST",
        "authority_chain": ["PRESSURE", "CONTEXT_RESOLUTION", "H4", "H1", "M15", "M1", "RISK"],
        "pressure": {
            "selected_pair": symbol,
            "lifecycle_id": lifecycle,
            "selection_confirmed": True,
        },
        "context_resolution": {
            "status": "RESOLVED",
            "origin": "WAIT_FOR_CONFIRMATION",
            "price_location": "H4_SUPPLY" if direction == "SELL" else "H4_DEMAND",
            "liquidity_context": "BUY_SIDE_REJECTED" if direction == "SELL" else "SELL_SIDE_REJECTED",
            "daily_bias": "BEARISH" if direction == "SELL" else "BULLISH",
            "h4_structure": f"{direction}_PULLBACK",
            "allowed_playbook": f"{direction}_ON_CONFIRMED_BREAK_RETEST",
            "selected_playbook": f"{direction}_ON_CONFIRMED_BREAK_RETEST",
            "blocked_playbook": [],
            "scenario_allowed": True,
        },
        "h4": {
            "target_mode": "FINAL_MARKET_STRUCTURE",
            "structural_tp1": target,
            "target_room_valid": True,
        },
        "h1": {
            "direction": direction,
            "structure_state": f"{direction}_CONFIRMED",
            "structure_confirmed": True,
            "candle_closed": True,
            "confirmed_at_utc": confirmed_at,
        },
        "m15": {
            "direction": direction,
            "structural_break": True,
            "candle_closed": True,
            "acceptance_confirmed": True,
            "failed_reclaim_or_retest_confirmed": False,
            "rejection_candle_only": False,
            "confirmed_at_utc": confirmed_at,
        },
        "m1": {
            "box_id": f"{lifecycle}:m1",
            "box_low": entry - 0.0001,
            "box_high": entry + 0.0001,
            "fill_price": entry,
            "return_to_box_invalidated": False,
        },
        "risk": {"structural_sl": stop, "sizing_basis": "STRUCTURAL_SL"},
    }
    return {
        "event": "signal_json",
        "symbol": symbol,
        "lifecycle_id": lifecycle,
        "final_direction": direction,
        "entry_reference_price": entry,
        "selected_sl": stop,
        "tp1": target,
        "strategy_5scr": proof,
    }


def test_confirmed_chfjpy_second_sell_is_execution_ready() -> None:
    evaluation = evaluate_strategy_5scr_proof(_signal())

    assert evaluation.ready is True
    assert evaluation.reasons == ()


def test_first_chfjpy_sell_is_no_trade_when_context_is_unresolved() -> None:
    signal = _signal()
    proof = deepcopy(signal["strategy_5scr"])
    proof["context_resolution"]["status"] = "WAIT_FOR_CONFIRMATION"
    proof["h1"]["structure_confirmed"] = False
    proof["m15"]["structural_break"] = False
    proof["m15"]["acceptance_confirmed"] = False
    proof["m15"]["rejection_candle_only"] = True
    signal["strategy_5scr"] = proof

    evaluation = evaluate_strategy_5scr_proof(signal)

    assert evaluation.decision == "DEFER"
    assert "NO_TRADE_CONTEXT_UNRESOLVED" in evaluation.reasons
    assert "NO_TRADE_REJECTION_CANDLE_ONLY" in evaluation.reasons


def test_nzdchf_remains_a_valid_strategy_trade_independent_of_loss_outcome() -> None:
    signal = _signal(symbol="NZDCHF", direction="BUY")

    evaluation = evaluate_strategy_5scr_proof(signal)

    assert evaluation.ready is True
    assert "outcome" not in signal["strategy_5scr"]


def test_blocked_playbook_fails_closed() -> None:
    signal = _signal()
    proof = deepcopy(signal["strategy_5scr"])
    proof["context_resolution"]["blocked_playbook"] = [
        proof["context_resolution"]["selected_playbook"]
    ]
    signal["strategy_5scr"] = proof

    evaluation = evaluate_strategy_5scr_proof(signal)

    assert evaluation.decision == "BLOCK"
    assert "STRATEGY_5SCR_PLAYBOOK_BLOCKED" in evaluation.reasons


def test_m1_return_to_box_invalidation_fails_closed() -> None:
    signal = _signal()
    proof = deepcopy(signal["strategy_5scr"])
    proof["m1"]["return_to_box_invalidated"] = True
    signal["strategy_5scr"] = proof

    evaluation = evaluate_strategy_5scr_proof(signal)

    assert evaluation.decision == "BLOCK"
    assert "STRATEGY_5SCR_M1_RETURN_TO_BOX_INVALIDATED" in evaluation.reasons


def test_tampered_rule_version_fails_schema_closed() -> None:
    signal = _signal()
    proof = deepcopy(signal["strategy_5scr"])
    proof["rule_version"] = "mutable-latest"
    signal["strategy_5scr"] = proof

    evaluation = evaluate_strategy_5scr_proof(signal)

    assert evaluation.decision == "BLOCK"
    assert evaluation.reasons == ("STRATEGY_5SCR_PROOF_SCHEMA_INVALID",)
