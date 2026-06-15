"""P2A Opsi A — market_structure + tradeplan_preview for EARLY_SELL_WATCH.

Flag-guarded (``SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED``) default OFF. Adds a
NON-EXECUTABLE structure + tradeplan preview to EARLY_SELL_WATCH watch payloads
(key levels, invalidation, SL/TP preview from market_context_snapshot). It NEVER
changes status / final_direction / requires_m15_close / valid_for_execution and
never emits a SignalJSON. Flag OFF must be byte-for-byte identical.
"""
from __future__ import annotations

import copy

from analysis.signal_json_emitter import build_signal_json_event
from analysis.signal_throttle_log_analyzer import _maybe_attach_structure_preview

_FLAG = "SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED"


def _early_sell_payload() -> dict:
    return {
        "status": "EARLY_SELL_WATCH",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "final_direction": "WAIT",
        "price_position": "MAIN_RESISTANCE",
        "entry_zone": [0.56988, 0.57012],
        "requires_m15_close": True,
        "valid_for_execution": False,
    }


def _complete_snapshot() -> dict:
    return {
        "key_resistance": 0.57012,
        "main_resistance": 0.57050,
        "resistance_high": 0.57050,
        "key_support": 0.56955,
        "main_support": 0.56931,
        "sl_safe": 0.57050,
        "sl_buffer": 0.57024,
        "tp1_support": 0.56955,
        "tp2_support": 0.56931,
        "tp3_support": 0.56854,
    }


# 1. flag OFF -> byte-for-byte unchanged
def test_flag_off_no_op(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    payload = _early_sell_payload()
    before = copy.deepcopy(payload)
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    assert payload == before
    assert "market_structure" not in payload
    assert "tradeplan_preview" not in payload


# 2. flag ON + EARLY_SELL + complete snapshot -> full preview
def test_flag_on_early_sell_complete(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["structure_bias"] == "SELL_REJECTION_WATCH"
    assert ms["price_position"] == "MAIN_RESISTANCE"
    assert ms["key_resistance"] == 0.57012
    assert ms["nearest_support"] == 0.56955
    assert ms["structure_ready"] is True
    assert tp["setup_type"] == "SELL_REJECTION_WATCH"
    assert tp["tp1"] == 0.56955
    assert tp["sl_safe"] == 0.57050
    assert tp["target_mode"] == "STRUCTURE_PREVIEW"
    assert tp["execution_usable"] is False


# 3. flag ON + non-EARLY_SELL -> unchanged
def test_flag_on_non_early_sell_unchanged(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    payload["status"] = "MICROBOOST_WATCH"
    before = copy.deepcopy(payload)
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    assert payload == before


# 4. flag ON + missing snapshot -> safe incomplete preview, no fabricated levels
def test_flag_on_missing_snapshot_incomplete(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    _maybe_attach_structure_preview(payload, None)
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["structure_ready"] is False
    assert tp["target_mode"] == "PREVIEW_CONTEXT_INCOMPLETE"
    assert tp["execution_usable"] is False
    assert "tp1" not in tp and "sl_safe" not in tp
    assert "key_resistance" not in ms


# 5. valid_for_execution stays false
def test_valid_for_execution_unchanged(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    assert payload["valid_for_execution"] is False


# 6. no final-signal flags introduced (proxy for SignalJSON stays 0)
def test_no_final_signal_flags(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    assert payload["tradeplan_preview"]["execution_usable"] is False
    assert payload.get("is_final_signal") in (None, False)
    assert payload["final_direction"] == "WAIT"


# 7. requires_m15_close unchanged
def test_requires_m15_close_unchanged(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    assert payload["requires_m15_close"] is True


# 8. emitter pass-through: both nested blocks survive build_signal_json_event
def test_emitter_preserves_market_structure(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    payload.update(
        {
            "symbol": "NZDCHF",
            "signal_valid_price": 0.56988,
            "entry_reference_price": 0.56988,
            "signal_valid_time_utc": "2026-06-15T00:00:00Z",
            "cluster_id": "NZDCHF_X",
            "market_context_applied": True,
        }
    )
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    event = build_signal_json_event(payload)
    assert event is not None
    d = event.to_dict()
    assert d["event"] == "signal_watch_json"
    assert d["market_structure"]["key_resistance"] == 0.57012
    assert d["tradeplan_preview"]["tp1"] == 0.56955
    assert d["valid_for_execution"] is not True


# 9. flag ON but emitter pass-through off-status leaves market_structure None
def test_emitter_market_structure_none_when_not_set(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    payload = _early_sell_payload()
    payload.update(
        {
            "symbol": "NZDCHF",
            "signal_valid_price": 0.56988,
            "entry_reference_price": 0.56988,
            "signal_valid_time_utc": "2026-06-15T00:00:00Z",
            "market_context_applied": True,
        }
    )
    event = build_signal_json_event(payload)
    assert event is not None
    assert event.to_dict().get("market_structure") is None
