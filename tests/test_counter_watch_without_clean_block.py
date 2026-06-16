"""Increment A - counter-entry watch without a 5-minute clean throttle block (flag-guarded).

When MICROBOOST_COUNTER_WATCH_WITHOUT_CLEAN_BLOCK=true, a directional ignition-class
microboost block at a main extreme reaches the counter engine even without a clean
throttle-block candidate, surfacing MICROBOOST_COUNTER_ENTRY / EARLY_SELL_WATCH
(27-May-style) instead of a generic MICROBOOST_WATCH -- while staying watch-only
(valid_for_execution=false). Default OFF -> behavior unchanged. The quality bar reuses
the vetted ignition-watch thresholds (>=18s, >=5 ticks, density >=8); sub-18s noise
is intentionally NOT promoted.
"""
from __future__ import annotations

from typing import Any

from analysis.signal_throttle_log_analyzer import _counter_entry_payload

_INELIGIBLE_GATE = {
    "eligible": False,
    "source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
    "reason": "MICROBOOST_PAIR_NOT_CLEAN_BLOCK_CANDIDATE",
}


def _summary(duration_seconds: float) -> dict[str, Any]:
    return {
        "latest": {
            "symbol": "NZDCHF",
            "direction": "BUY",
            "phase_priced": "RESISTANCE_PRESSURE_WARNING",
            "price_position": "MAIN_RESISTANCE",
            "market_context_applied": True,
            "market_context_snapshot": {
                "price_at_signal_start": 0.46490,
                "price_at_signal_end": 0.46504,
                "price_position": "MAIN_RESISTANCE",
                "m15_phase": "BULLISH_PULLBACK",
                "h1_phase": "BEARISH",
            },
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BEARISH",
            "effective_density": 45.17,
            "effective_ticks": 8,
            "duration_seconds": duration_seconds,
            "end_utc": "2026-06-10T08:35:37+00:00",
            "cluster_id": "NZDCHF_20260610T083500Z",
        }
    }


def _status(payload: dict[str, Any] | None) -> str:
    return str((payload or {}).get("status") or "NONE")


def test_flag_off_keeps_blocked_none(monkeypatch):
    monkeypatch.delenv("MICROBOOST_COUNTER_WATCH_WITHOUT_CLEAN_BLOCK", raising=False)
    payload = _counter_entry_payload(_summary(20.0), dict(_INELIGIBLE_GATE))
    assert _status(payload) == "NONE"


def test_flag_on_ignition_block_becomes_counter_sell_watch(monkeypatch):
    monkeypatch.setenv("MICROBOOST_COUNTER_WATCH_WITHOUT_CLEAN_BLOCK", "true")
    payload = _counter_entry_payload(_summary(20.0), dict(_INELIGIBLE_GATE))
    assert payload is not None
    assert payload["signal_family"] == "MICROBOOST_COUNTER_ENTRY"
    assert _status(payload).endswith("SELL_WATCH")
    assert payload["candidate_direction"] == "SELL"
    assert payload["final_direction"] == "WAIT"
    assert payload["valid_for_execution"] is False
    # honest: no clean-block confirmation backed this watch
    assert payload["source_clean_block_confirmed"] is False


def test_flag_on_short_burst_stays_blocked(monkeypatch):
    monkeypatch.setenv("MICROBOOST_COUNTER_WATCH_WITHOUT_CLEAN_BLOCK", "true")
    payload = _counter_entry_payload(_summary(2.0), dict(_INELIGIBLE_GATE))  # 2s < 18s bar
    assert _status(payload) == "NONE"
