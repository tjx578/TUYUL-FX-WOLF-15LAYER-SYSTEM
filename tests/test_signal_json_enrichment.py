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
    assert enriched["tp1"] == 1.8666
    assert enriched["tp1_rr"] == 1.5
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
    assert enriched["targets"][0]["level"] == 1.8666
    assert enriched["targets"][1]["level"] == 1.869
    assert enriched["tradeplan_valid"] is True
    assert enriched["valid_for_execution"] is True


def test_watch_payload_with_null_nested_objects_exports_safe_containers():
    source = {
        "symbol": "GBPCAD",
        "status": "SELL_ABSORPTION_WATCH",
        "final_direction": "WAIT",
        "target_mode": "PROVISIONAL_RR_FALLBACK",
        "targets": None,
        "target_policy": None,
        "structure_zones": None,
        "risk_reward": None,
        "invalidation_rules": None,
        "execution_quality": None,
        "phase_coherence": None,
        "signal_expiry": None,
        "audit_block_reasons": None,
    }

    enriched = enrich_signal_json_payload(source)

    assert enriched["targets"] == []
    assert enriched["structure_zones"] == {}
    assert enriched["risk_reward"] == {}
    assert enriched["invalidation_rules"] == {}
    assert enriched["execution_quality"] == {}
    assert enriched["phase_coherence"] == {}
    assert enriched["signal_expiry"] == {}
    assert enriched["audit_block_reasons"] == []


def test_legacy_structure_tp_fields_remain_usable_when_targets_was_null():
    source = {
        "symbol": "GBPCAD",
        "status": "BUY_BREAKOUT_CONTINUATION_VALID",
        "final_direction": "BUY",
        "signal_valid_time_utc": "2026-05-25T08:05:54+00:00",
        "entry_reference_price": 1.8636,
        "entry_zone": [1.8628, 1.8640],
        "m15_phase": "BULLISH_PULLBACK",
        "h1_phase": "BULLISH",
        "sl_safe": 1.8616,
        "key_support": 1.8616,
        "key_resistance": 1.8650,
        "target_mode": "FINAL_MARKET_STRUCTURE",
        "targets": None,
        "tp3": 1.8690,
        "execution_quality": {"spread_normal": True},
        "valid_for_execution": True,
    }

    enriched = enrich_signal_json_payload(source)

    assert enriched["targets"][0]["type"] == "FIXED_RR"
    assert enriched["targets"][1]["type"] == "STRUCTURE_TARGET"
    assert enriched["targets"][1]["level"] == 1.869
    assert enriched["tradeplan_valid"] is True
