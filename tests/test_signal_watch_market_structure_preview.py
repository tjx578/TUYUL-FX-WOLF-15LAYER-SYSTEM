"""P2A Opsi A — market_structure + tradeplan_preview for EARLY_SELL_WATCH.

Flag-guarded (``SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED``) default OFF. Adds a
NON-EXECUTABLE structure + tradeplan preview to EARLY_SELL_WATCH watch payloads.

SL is a STRUCTURAL INVALIDATION level only (price above entry for a SELL) -- never a
fixed buffer (no ``sl_tight``/``sl_safe``). TP1 must satisfy RR >= 1.5 vs the structural
SL; a nearer support that does not is surfaced as ``nearby_structure_marker``. When no
valid structural invalidation exists, ``sl=None`` and the preview is incomplete. It NEVER
changes status / final_direction / requires_m15_close / valid_for_execution and never
emits a SignalJSON. Flag OFF must be byte-for-byte identical.
"""
from __future__ import annotations

import copy

import pytest

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
        "entry_zone": [0.56988],
        "signal_valid_price": 0.56988,
        "entry_reference_price": 0.56988,
        "requires_m15_close": True,
        "valid_for_execution": False,
    }


def _complete_snapshot() -> dict:
    # entry 0.56988 ; SL = resistance_high 0.57100 -> risk 11.2 pips.
    # tp1_support 0.56960 is only 0.25R -> nearby marker (rejected as TP1).
    # tp2_support 0.56800 is 1.68R -> tp1 ; tp3_support 0.56700 -> tp2.
    return {
        "resistance_high": 0.57100,
        "key_resistance": 0.57050,
        "main_resistance": 0.57080,
        "key_support": 0.56955,
        "main_support": 0.56931,
        "tp1_support": 0.56960,
        "tp2_support": 0.56800,
        "tp3_support": 0.56700,
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


# 2. flag ON + EARLY_SELL + complete snapshot -> structural SL + RR-valid targets
def test_flag_on_early_sell_complete(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["structure_bias"] == "SELL_REJECTION_WATCH"
    assert ms["price_position"] == "MAIN_RESISTANCE"
    assert ms["key_resistance"] == 0.57050
    assert ms["invalidation_level"] == 0.57100
    assert ms["nearest_support"] == 0.56955
    assert ms["structure_ready"] is True
    # structural SL only -- no buffer fields
    assert tp["sl"] == 0.57100
    assert tp["sl_source"] == "MARKET_STRUCTURE_RESISTANCE_HIGH"
    assert tp["invalidation_level"] == 0.57100
    assert "sl_tight" not in tp
    assert "sl_safe" not in tp
    # RR>=1.5 filter: nearest support rejected as TP1, surfaced as marker
    assert tp["nearby_structure_marker"] == 0.56960
    assert tp["tp1"] == 0.56800
    assert tp["tp2"] == 0.56700
    assert "tp3" not in tp
    assert tp["risk_pips"] == pytest.approx(11.2, abs=0.05)
    assert tp["rr_to_tp1"] == pytest.approx(1.68, abs=0.02)
    assert tp["rr_to_tp1"] >= 1.5
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


# 4. flag ON + missing snapshot -> incomplete, explicit sl=None, no fabricated levels
def test_flag_on_missing_snapshot_incomplete(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    _maybe_attach_structure_preview(payload, None)
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["structure_ready"] is False
    assert tp["target_mode"] == "PREVIEW_CONTEXT_INCOMPLETE"
    assert tp["execution_usable"] is False
    assert tp["sl"] is None
    assert tp["sl_source"] == "MISSING_STRUCTURE_INVALIDATION"
    assert "tp1" not in tp
    assert "risk_pips" not in tp
    assert "key_resistance" not in ms


# 4b. no structural invalidation above entry -> sl=None even with a (below-entry) level
def test_no_invalidation_above_entry(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    payload = _early_sell_payload()
    # all resistance levels are BELOW entry -> not a valid SELL invalidation
    snap = {"resistance_high": 0.56900, "key_resistance": 0.56880, "tp1_support": 0.56700}
    _maybe_attach_structure_preview(payload, snap)
    tp = payload["tradeplan_preview"]
    assert tp["sl"] is None
    assert tp["sl_source"] == "MISSING_STRUCTURE_INVALIDATION"
    assert tp["target_mode"] == "PREVIEW_CONTEXT_INCOMPLETE"


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
    assert d["market_structure"]["invalidation_level"] == 0.57100
    assert d["tradeplan_preview"]["sl"] == 0.57100
    assert d["tradeplan_preview"]["tp1"] == 0.56800
    assert d["valid_for_execution"] is not True


# 9. flag OFF -> emitter leaves market_structure None (no field introduced)
def test_emitter_market_structure_none_when_not_set(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    payload = _early_sell_payload()
    payload.update(
        {
            "symbol": "NZDCHF",
            "signal_valid_time_utc": "2026-06-15T00:00:00Z",
            "market_context_applied": True,
        }
    )
    event = build_signal_json_event(payload)
    assert event is not None
    assert event.to_dict().get("market_structure") is None


# ----------------------------------------------------------------------------
# P2A-General: market_structure_status + structure_pending_reason for ALL watches
# ----------------------------------------------------------------------------
_GEN_FLAG = "SIGNAL_WATCH_MARKET_STRUCTURE_STATUS_ENABLED"


def _gbpcad_watch() -> dict:
    # raw BUY pressure but H1 downtrend + M15 lower-high + mid-range -> structure pending
    return {
        "status": "MICROBOOST_WATCH",
        "signal_family": "MICROBOOST_WATCH",
        "raw_direction": "BUY",
        "candidate_direction": "BUY",
        "watch_direction": "BUY",
        "final_direction": "WAIT",
        "price_position": "MID_RANGE",
        "m15_phase": "LOWER_HIGH",
        "h1_phase": "DOWNTREND",
        "entry_zone": [1.87585],
        "signal_valid_price": 1.87585,
        "entry_reference_price": 1.87585,
        "requires_m15_close": False,
        "valid_for_execution": False,
    }


def _buy_ready_snapshot() -> dict:
    # entry 1.87585 ; SL = support_low 1.87390 (19.5 pips) ; resistance ladder above.
    return {
        "support_low": 1.87390,
        "key_support": 1.87390,
        "main_support": 1.87300,
        "key_resistance": 1.87900,
        "tp1_resistance": 1.87620,  # 0.18R -> nearby marker
        "tp2_resistance": 1.87900,  # 1.62R -> tp1
        "tp3_resistance": 1.88100,  # 2.64R -> tp2
    }


# G1. general flag ON + GBPCAD-like -> STRUCTURE_PENDING + reasons, no fabricated SL/TP
def test_general_pending_structure_with_reasons(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _gbpcad_watch()
    _maybe_attach_structure_preview(payload, {})
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["market_structure_status"] == "STRUCTURE_PENDING"
    assert ms["structure_class"] == "BUY_RECLAIM_REQUIRED"
    assert "H1_DOWNTREND_CONFLICT" in ms["structure_pending_reason"]
    assert "M15_LOWER_HIGH_NOT_RECLAIMED" in ms["structure_pending_reason"]
    assert "MID_RANGE_NO_STRUCTURAL_ENTRY_ZONE" in ms["structure_pending_reason"]
    assert "STRUCTURAL_SL_NOT_AVAILABLE" in ms["structure_pending_reason"]
    assert tp["sl"] is None
    assert tp["sl_source"] == "MISSING_STRUCTURE_INVALIDATION"
    assert tp["target_mode"] == "PREVIEW_CONTEXT_INCOMPLETE"
    assert tp["execution_usable"] is False
    # safety untouched
    assert payload["valid_for_execution"] is False
    assert payload["requires_m15_close"] is False
    assert payload["final_direction"] == "WAIT"


# G2. general flag ON + BUY structure ready -> structural SL BELOW entry + TP ABOVE + RR
def test_general_buy_structure_ready(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _gbpcad_watch()
    payload["price_position"] = "MAIN_SUPPORT"
    payload["h1_phase"] = "UPTREND"
    payload["m15_phase"] = "HIGHER_LOW"
    _maybe_attach_structure_preview(payload, _buy_ready_snapshot())
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["market_structure_status"] == "STRUCTURE_READY"
    assert ms["structure_class"] == "COUNTER_PRESSURE_AT_SUPPORT"
    assert tp["sl"] == 1.87390  # support below entry
    assert tp["sl_source"] == "MARKET_STRUCTURE_SUPPORT_LOW"
    assert tp["sl"] < payload["signal_valid_price"]
    assert tp["nearby_structure_marker"] == 1.87620
    assert tp["tp1"] == 1.87900  # resistance above entry, RR>=1.5
    assert tp["tp1"] > payload["signal_valid_price"]
    assert tp["rr_to_tp1"] >= 1.5
    assert tp["risk_pips"] == pytest.approx(19.5, abs=0.1)
    assert tp["execution_usable"] is False


def test_xauusd_preview_normalizes_pips_points_and_blocks_tp_inside_entry_zone(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _gbpcad_watch()
    payload.update(
        {
            "symbol": "XAUUSD",
            "entry_zone": [4123.005, 4125.35],
            "signal_valid_price": 4123.005,
            "entry_reference_price": 4123.005,
            "m15_phase": "BEARISH_PULLBACK",
            "h1_phase": "BEARISH",
            "price_position": "MID_RANGE",
            "requires_m15_close": False,
            "signal_valid_time_utc": "2026-07-10T03:27:36.636902+00:00",
            "market_context_applied": True,
        }
    )
    snap = {
        "support_low": 4122.055,
        "key_support": 4122.745,
        "key_resistance": 4138.06,
        "tp1_resistance": 4125.24,
        "tp2_resistance": 4125.745,
    }

    _maybe_attach_structure_preview(payload, snap)

    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert tp["risk_pips"] == pytest.approx(95.0, abs=0.01)
    assert tp["risk_points"] == pytest.approx(9500.0, abs=0.01)
    assert tp["pip_size"] == 0.01
    assert tp["point_size"] == pytest.approx(0.0001, abs=0.0000001)
    assert tp["display_unit"] == "pips"
    assert tp["preview_block_reason"] == "TP1_INSIDE_ENTRY_ZONE"
    assert tp["tradeplan_preview_valid_for_display"] is False
    assert tp["rr_to_tp1_display_valid"] is False
    assert "rr_to_tp1" not in tp
    assert "TP1_INSIDE_ENTRY_ZONE" in ms["structure_pending_reason"]
    assert payload["requires_reclaim_confirmation"] is True
    assert payload["requires_support_hold_confirmation"] is True
    assert payload["requires_breakdown_confirmation"] is True
    assert payload["valid_for_execution"] is False
    event = build_signal_json_event(payload)
    assert event is not None
    assert event.requires_reclaim_confirmation is True
    assert event.requires_support_hold_confirmation is True
    assert event.requires_breakdown_confirmation is True


# G3. general flag ON + no candidate direction -> DIRECTION_NOT_RESOLVED
def test_general_direction_not_resolved(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _gbpcad_watch()
    payload["candidate_direction"] = None
    payload["watch_direction"] = None
    _maybe_attach_structure_preview(payload, {})
    ms = payload["market_structure"]
    assert ms["market_structure_status"] == "STRUCTURE_PENDING"
    assert ms["structure_class"] == "DIRECTION_PENDING"
    assert "DIRECTION_NOT_RESOLVED" in ms["structure_pending_reason"]
    assert payload["tradeplan_preview"]["execution_usable"] is False


# G4. general flag ON + EARLY_SELL -> STRUCTURE_READY via shared SELL core
def test_general_early_sell_uses_shared_core(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _early_sell_payload()
    _maybe_attach_structure_preview(payload, _complete_snapshot())
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["market_structure_status"] == "STRUCTURE_READY"
    assert ms["structure_class"] == "COUNTER_PRESSURE_AT_RESISTANCE"
    assert tp["sl"] == 0.57100  # same structural SL as P2A Opsi A
    assert tp["tp1"] == 0.56800


# G5. both flags OFF -> byte-for-byte no-op
def test_general_flag_off_no_op(monkeypatch):
    monkeypatch.delenv(_GEN_FLAG, raising=False)
    monkeypatch.delenv(_FLAG, raising=False)
    payload = _gbpcad_watch()
    before = copy.deepcopy(payload)
    _maybe_attach_structure_preview(payload, _buy_ready_snapshot())
    assert payload == before


# G6. general flag ON + non-watch status -> unchanged
def test_general_non_watch_unchanged(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _gbpcad_watch()
    payload["status"] = "NO_TRADE_REASONED"
    before = copy.deepcopy(payload)
    _maybe_attach_structure_preview(payload, _buy_ready_snapshot())
    assert payload == before


# G7. degenerate micro-box: SL ~1.4 pips (RR in-band) -> held PENDING, not fake READY
def _tiny_sl_early_sell() -> dict:
    return {
        "status": "EARLY_SELL_WATCH",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "watch_direction": "SELL",
        "final_direction": "WAIT",
        "price_position": "MAIN_RESISTANCE",
        "h1_phase": "DOWNTREND",
        "m15_phase": "BULLISH_PULLBACK",
        "entry_zone": [0.99026, 0.99034],
        "signal_valid_price": 0.99034,
        "entry_reference_price": 0.99034,
        "requires_m15_close": True,
        "valid_for_execution": False,
        "pair_calibration": {"pip_size": 0.0001},
    }


def test_tiny_absolute_sl_held_pending(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _tiny_sl_early_sell()
    # SL 0.99048 is 1.4 pips above entry; tp1 0.99008 gives RR 1.86 (in band) but the SL is noise.
    snap = {
        "resistance_high": 0.99048,
        "key_resistance": 0.99048,
        "key_support": 0.99008,
        "tp1_support": 0.99008,
        "tp2_support": 0.98729,
        "tp3_support": 0.98516,
    }
    _maybe_attach_structure_preview(payload, snap)
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["market_structure_status"] == "STRUCTURE_PENDING"
    assert ms["structure_ready"] is False
    assert "STRUCTURAL_SL_TOO_TIGHT" in ms["structure_pending_reason"]
    assert tp["target_mode"] == "PREVIEW_CONTEXT_INCOMPLETE"
    assert tp["risk_pips"] < 3.0  # noise-level distance, not a structural invalidation
    assert tp["execution_usable"] is False


# G8. m15-range volatility floor: a 4-pip SL in a wide-range candle is still too tight
def test_volatility_relative_sl_floor(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _tiny_sl_early_sell()
    payload["signal_valid_price"] = 0.99034
    payload["entry_reference_price"] = 0.99034
    # SL 4 pips, but M15 range ~30 pips -> 0.4*30 = 12 pip floor -> still too tight.
    snap = {
        "resistance_high": 0.99074,  # 4 pips above entry
        "key_resistance": 0.99074,
        "key_support": 0.98900,
        "tp1_support": 0.98900,  # ~13 pips -> RR ~3.3 (in band)
        "m15_high": 0.99200,
        "m15_low": 0.98900,  # 30-pip M15 range
    }
    _maybe_attach_structure_preview(payload, snap)
    assert payload["market_structure"]["market_structure_status"] == "STRUCTURE_PENDING"
    assert "STRUCTURAL_SL_TOO_TIGHT" in payload["market_structure"]["structure_pending_reason"]


# G7. degenerate structure (SL noise-tight, RR implausible) -> PENDING + STRUCTURAL_SL_TOO_TIGHT.
# Real GBPCAD case: SL 4.7 pips above entry (resistance_high==key_resistance, ladder missing),
# TP1 49 pips away -> RR 10.49. Must NOT be presented as STRUCTURE_READY.
def test_general_degenerate_sl_too_tight(monkeypatch):
    monkeypatch.setenv(_GEN_FLAG, "true")
    payload = _early_sell_payload()
    payload["signal_valid_price"] = 1.87801
    payload["entry_reference_price"] = 1.87801
    snap = {
        "resistance_high": 1.87848,
        "key_resistance": 1.87848,
        "key_support": 1.87770,
        "tp1_support": 1.87770,
        "tp2_support": 1.87308,
    }
    _maybe_attach_structure_preview(payload, snap)
    ms = payload["market_structure"]
    tp = payload["tradeplan_preview"]
    assert ms["market_structure_status"] == "STRUCTURE_PENDING"
    assert ms["structure_ready"] is False
    assert "STRUCTURAL_SL_TOO_TIGHT" in ms["structure_pending_reason"]
    assert tp["rr_to_tp1"] > 6.0  # the implausible RR that exposed the degenerate SL
    assert tp["target_mode"] == "PREVIEW_CONTEXT_INCOMPLETE"
    assert tp["execution_usable"] is False
