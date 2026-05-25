from __future__ import annotations

from analysis.signal_json_enrichment import enrich_signal_json_payload


def test_log_enrichment_does_not_mutate_core_breakout_decision():
    source = {
        "symbol": "GBPCAD",
        "status": "BUY_BREAKOUT_CONTINUATION_VALID",
        "final_direction": "BUY",
        "action": "BUY_BREAKOUT_RETEST",
        "signal_valid_time_utc": "2026-05-25T08:05:54+00:00",
        "signal_valid_price": 1.8636,
        "entry_reference_price": 1.8636,
        "entry_zone": [1.8636, 1.8636],
        "price_position": "MAIN_RESISTANCE",
        "m15_phase": "BULLISH_PULLBACK",
        "h1_phase": "BULLISH",
        "sl_tight": 1.8624,
        "sl_safe": 1.8616,
        "tp1": 1.8648,
        "tp1_rr": 0.6,
        "target_mode": "PROVISIONAL_RR_FALLBACK",
        "valid_for_execution": True,
    }

    enriched = enrich_signal_json_payload(source)

    assert source["status"] == "BUY_BREAKOUT_CONTINUATION_VALID"
    assert source["tp1"] == 1.8648
    assert enriched["status"] == source["status"]
    assert enriched["final_direction"] == source["final_direction"]
    assert enriched["action"] == source["action"]
    assert enriched["source_valid_for_execution"] is True
    assert enriched["selected_sl"] == 1.8616
    assert enriched["selected_risk_pips"] == 20.0
    assert enriched["tp1"] == 1.8676
    assert enriched["tp1_rr"] == 2.0
    assert enriched["valid_for_execution"] is False
    assert enriched["execution_status"] == "WAIT_STRUCTURE_COMPLETION"


def test_structure_complete_output_can_remain_executable_without_changing_signal():
    source = {
        "symbol": "GBPCAD",
        "status": "BUY_BREAKOUT_CONTINUATION_VALID",
        "final_direction": "BUY",
        "action": "BUY_BREAKOUT_RETEST",
        "signal_valid_time_utc": "2026-05-25T08:05:54+00:00",
        "signal_valid_price": 1.8636,
        "entry_reference_price": 1.8636,
        "entry_zone": [1.8628, 1.8640],
        "price_position": "MAIN_RESISTANCE",
        "m15_phase": "BULLISH_PULLBACK",
        "h1_phase": "BULLISH",
        "sl_tight": 1.8624,
        "sl_safe": 1.8616,
        "key_support": 1.8616,
        "key_resistance": 1.8650,
        "target_mode": "FINAL_MARKET_STRUCTURE",
        "targets": [{"id": "TP2", "type": "STRUCTURE_TARGET", "level": 1.8690}],
        "execution_quality": {"spread_normal": True},
        "valid_for_execution": True,
    }

    enriched = enrich_signal_json_payload(source)

    assert enriched["status"] == "BUY_BREAKOUT_CONTINUATION_VALID"
    assert enriched["final_direction"] == "BUY"
    assert enriched["targets"][0]["level"] == 1.8676
    assert enriched["targets"][1]["level"] == 1.869
    assert enriched["tradeplan_valid"] is True
    assert enriched["valid_for_execution"] is True
