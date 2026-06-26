from __future__ import annotations

import json
import logging
from typing import Any, cast

from analysis.market_context_validator import MarketContext
from analysis.microboost_continuation_entry import MicroboostContinuationEngine
from analysis.signal_json_emitter import SignalJsonEmitter
from analysis.signal_json_gate_adapter import SignalJsonGateAdapter
from analysis.signal_lifecycle_manager import SignalLifecycleManager
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


def _continuation_payload() -> dict:
    cluster = {
        "cluster_id": "USDCAD_20260520T024532Z",
        "symbol": "USDCAD",
        "direction": "BUY",
        "phase_unpriced": "IGNITION_MICROBOOST",
        "phase_priced": "TREND_CONTINUATION_MICROBOOST",
        "effective_density_per_minute": 31.68,
        "effective_tick_count": 32,
        "duration_seconds": 62.0,
        "start_utc": "2026-05-20T02:45:32+00:00",
        "end_utc": "2026-05-20T02:46:34+00:00",
        "price_position": "MID_RANGE",
        "market_context_snapshot": {
            "symbol": "USDCAD",
            "raw_allowed_direction": "BUY",
            "pip_value": 0.0001,
            "price_at_signal_start": 1.37560,
            "price_at_signal_end": 1.375675,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BULLISH",
            "spread_normal": True,
            "price_position": "MID_RANGE",
            "main_support": 1.3720,
            "main_resistance": 1.3850,
            "minor_resistance": 1.3785,
            "tp1_resistance": 1.3785,
            "tp2_resistance": 1.3810,
            "tp3_resistance": 1.3850,
        },
    }
    quorum = {"symbol": "USDCAD", "direction": "BUY", "streak": 3, "quorum_size": 3, "quorum_reached": True}
    return MicroboostContinuationEngine().evaluate(cluster, allowed_quorum=quorum).to_dict()


def _finalizer_final_sell_payload() -> dict:
    return {
        "symbol": "USDCAD",
        "cluster_id": "USDCAD_20260521T030620Z",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "status": "SELL_TIMING_VALID",
        "previous_status": "SELL_ABSORPTION_WATCH",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "validated_direction": "SELL",
        "watch_direction": "SELL",
        "final_direction": "SELL",
        "direction_validation_status": "VALIDATED_EXECUTION",
        "action": "EXECUTE_SELL_STRUCTURE_TARGET",
        "signal_valid_time_utc": "2026-05-21T03:09:22+00:00",
        "signal_valid_price": 1.37633,
        "entry_reference_price": 1.37633,
        "entry_zone": [1.37633, 1.37647],
        "price_position": "MAIN_RESISTANCE",
        "m15_phase": "BEARISH_PULLBACK",
        "h1_phase": "BEARISH",
        "rr_status": "VALID",
        "target_mode": "STRUCTURE_LADDER_TARGET",
        "target_source": "support_resistance_ladder",
        "market_context_applied": True,
        "valid_for_execution": True,
        "selected_sl": 1.37807,
        "sl_safe": 1.37807,
        "tp1": 1.3738,
        "tp2": 1.3730,
        "tp1_rr": 1.45,
        "tp2_rr": 1.91,
        "tp_min_rr": 1.373,
        "tp_min_rr_value": 1.91,
        "rr_to_valid_target": 1.91,
        "min_rr_required": 1.5,
        "main_support": 1.3730,
        "main_resistance": 1.37647,
        "key_support": 1.3730,
        "key_resistance": 1.37647,
        "spread_normal": True,
        "theme_aligned": True,
        "tradeplan_context_ready": True,
        "targets_execution_usable": True,
        "tradeplan_valid": True,
        "execution_valid_now": True,
        "signal_valid": True,
        "direction_valid": True,
        "analysis_valid": True,
        "promotion_path": "WATCH_TO_FINAL",
        "pending_decision_id": "USDCAD_20260521T030620Z_M15_DECISION",
        "reason": "M15 rejection confirmed with structure ladder ready.",
    }


class _StaticFinalizer:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.tracked: list[dict] = []

    def finalize(self, **_kwargs: Any) -> list[dict]:
        return [self.payload]

    def track(self, payload: dict) -> None:
        self.tracked.append(payload)


def test_pipeline_emits_valid_continuation_payload_by_default():
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_lifecycle_manager = SignalLifecycleManager()
    emitted: list[dict] = []
    pipeline._emit_signal_json_payload = lambda payload: emitted.append(payload) or True

    report = {"microboost_continuation_entry": _continuation_payload()}
    verdict: dict = {}

    pipeline._apply_microboost_continuation_entry_report(l12_verdict=verdict, report=report)

    assert emitted
    assert emitted[0]["status"] == "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION"
    assert emitted[0]["signal_json_emit_result"] is True
    assert emitted[0]["rr_to_valid_target"] >= emitted[0]["min_rr_required"]
    assert report["microboost_continuation_entry"]["signal_id"]


def test_pipeline_logs_valid_continuation_as_signal_json(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_lifecycle_manager = SignalLifecycleManager()
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True)

    report = {"microboost_continuation_entry": _continuation_payload()}
    verdict: dict = {}

    pipeline._apply_microboost_continuation_entry_report(l12_verdict=verdict, report=report)

    assert "[SignalJSON]" in caplog.text
    assert '"status":"FINAL_EXECUTION_READY"' in caplog.text
    assert '"source_status":"BUY_TIMING_VALID_BY_QUORUM_CONTINUATION"' in caplog.text
    assert '"signal_valid":true' in caplog.text
    assert '"execution_valid_now":true' in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text


def test_pipeline_logs_generic_microboost_watch_as_signal_watch_json(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True, emit_watch=True)

    report = {
        "microboost_watch_entry": {
            "symbol": "CADJPY",
            "cluster_id": "CADJPY_20260518T133000Z",
            "signal_family": "MICROBOOST_WATCH",
            "status": "MICROBOOST_WATCH",
            "raw_direction": "BUY",
            "candidate_direction": "BUY",
            "validated_direction": None,
            "watch_direction": "BUY",
            "final_direction": "WAIT",
            "action": "WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION",
            "signal_valid_time_utc": "2026-05-18T13:32:29+00:00",
            "signal_valid_price": 115.5235,
            "entry_reference_price": 115.5235,
            "entry_zone": [115.5, 115.5235],
            "phase_unpriced": "DENSE_MICROBOOST",
            "phase_priced": "BULLISH_PULLBACK_MICROBOOST",
            "rr_status": "WATCH",
            "market_context_applied": True,
            "valid_for_execution": False,
            "reason": "microboost waits for M15 reclaim",
        }
    }
    verdict: dict = {}

    pipeline._apply_microboost_watch_entry_report(l12_verdict=verdict, report=report)

    assert "[SignalWatchJSON]" in caplog.text
    assert '"status":"MICROBOOST_WATCH"' in caplog.text
    assert '"signal_family":"MICROBOOST_WATCH"' in caplog.text
    assert verdict["microboost_watch_entry"]["status"] == "MICROBOOST_WATCH"
    assert verdict["microboost_watch_entry"]["signal_json_emit_result"] is True
    assert verdict["microboost_watch_entry"]["lifecycle_track"] is True
    assert verdict["microboost_watch_entry"]["terminal_required"] is True
    assert verdict["microboost_watch_entry"]["pending_decision_id"]


def test_pipeline_logs_clean_block_watch_entries_as_signal_watch_json(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True, emit_watch=True)

    report = {
        "clean_block_watch_entries": [
            {
                "symbol": "USDCAD",
                "cluster_id": "USDCAD_20260623T050049Z_20260623T055702Z",
                "signal_family": "CLEAN_BLOCK_BUY_WATCH",
                "status": "CLEAN_BLOCK_BUY_WATCH",
                "raw_direction": "BUY",
                "candidate_direction": "BUY",
                "validated_direction": None,
                "watch_direction": "BUY",
                "final_direction": "WAIT",
                "action": "WAIT_PRICE_THEME_STRUCTURE",
                "signal_valid_time_utc": "2026-06-23T05:57:02+00:00",
                "signal_valid_price": 1.3740,
                "entry_reference_price": 1.3740,
                "entry_zone": [1.3730, 1.3740],
                "rr_status": "UNVALIDATED",
                "market_context_applied": True,
                "valid_for_execution": False,
                "signal_quality": "WATCH_ONLY",
                "reason": "clean_block_router_promoted_valid_clean_block_to_signal_watch",
                "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
                "source_clean_block_confirmed": True,
                "source_clean_block_id": "USDCAD_20260623T050049Z_20260623T055702Z",
                "source_pressure_block_id": "USDCAD_20260623T050049Z_20260623T055702Z",
                "clean_block_valid": True,
                "clean_block_direction": "BUY",
                "watch_promotion_source": "CLEAN_BLOCK_ROUTER",
            }
        ]
    }
    verdict: dict = {}

    pipeline._apply_clean_block_watch_routes(l12_verdict=verdict, report=report)

    assert "[SignalWatchJSON]" in caplog.text
    assert '"status":"CLEAN_BLOCK_BUY_WATCH"' in caplog.text
    assert report["clean_block_watch_entries"][0]["signal_json_emit_result"] is True
    assert verdict["clean_block_watch_entries"][0]["source_clean_block_id"]


def test_pipeline_emits_signal_watch_promotion_diagnostic(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    monkeypatch.setenv("SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_ENABLED", "true")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    report = {
        "signal_watch_promotion_diagnostics": [
            {
                "event": "signal_watch_promotion_diagnostic",
                "symbol": "GBPNZD",
                "source_clean_block_id": "GBPNZD_20260623T060000Z_20260623T065800Z",
                "clean_block_valid": True,
                "eligible_for_signal_watch": False,
                "blocked_by": ["MARKET_CONTEXT_MISSING"],
                "next_required_stage": "HYDRATE_MARKET_CONTEXT",
                "valid_for_execution": False,
                "is_final_signal": False,
                "final_direction": "WAIT",
            }
        ]
    }
    verdict: dict = {}

    pipeline._apply_clean_block_watch_routes(l12_verdict=verdict, report=report)

    assert "[SignalWatchPromotionDiagnostic]" in caplog.text
    assert '"event":"signal_watch_promotion_diagnostic"' in caplog.text
    assert report["signal_watch_promotion_diagnostics"][0]["diagnostic_emit_result"] is True
    assert verdict["signal_watch_promotion_diagnostics"][0]["next_required_stage"] == "HYDRATE_MARKET_CONTEXT"


def test_pipeline_tracks_official_watch_only_after_successful_emit():
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    emitted: list[dict] = []
    pipeline._emit_signal_json_payload = lambda payload: emitted.append(payload) or True

    class _Tracker:
        def __init__(self) -> None:
            self.tracked: list[dict] = []

        def track(self, payload: dict) -> None:
            self.tracked.append(payload)

    tracker = _Tracker()
    cast(Any, pipeline)._signal_block_finalizer = tracker
    report = {
        "microboost_watch_entry": {
            "symbol": "CADJPY",
            "cluster_id": "CADJPY_20260518T133000Z",
            "signal_family": "MICROBOOST_WATCH",
            "status": "MICROBOOST_WATCH",
            "candidate_direction": "BUY",
            "watch_direction": "BUY",
            "final_direction": "WAIT",
            "signal_valid_time_utc": "2026-05-18T13:32:29+00:00",
            "signal_valid_price": 115.5235,
            "entry_reference_price": 115.5235,
            "entry_zone": [115.5, 115.5235],
            "signal_quality": "WATCH_ONLY",
            "source_clean_block_confirmed": True,
            "valid_for_execution": False,
        }
    }
    verdict: dict = {}

    pipeline._apply_microboost_watch_entry_report(l12_verdict=verdict, report=report)

    assert emitted
    assert emitted[0]["lifecycle_track"] is True
    assert tracker.tracked == [verdict["microboost_watch_entry"]]


def test_pipeline_does_not_track_watch_when_emit_fails():
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._emit_signal_json_payload = lambda payload: False

    class _Tracker:
        def __init__(self) -> None:
            self.tracked: list[dict] = []

        def track(self, payload: dict) -> None:
            self.tracked.append(payload)

    tracker = _Tracker()
    cast(Any, pipeline)._signal_block_finalizer = tracker
    report = {
        "microboost_watch_entry": {
            "symbol": "CADJPY",
            "cluster_id": "CADJPY_20260518T133000Z",
            "signal_family": "MICROBOOST_WATCH",
            "status": "MICROBOOST_WATCH",
            "candidate_direction": "BUY",
            "watch_direction": "BUY",
            "final_direction": "WAIT",
            "signal_valid_time_utc": "2026-05-18T13:32:29+00:00",
            "signal_valid_price": 115.5235,
            "entry_reference_price": 115.5235,
            "entry_zone": [115.5, 115.5235],
            "signal_quality": "WATCH_ONLY",
            "source_clean_block_confirmed": True,
            "valid_for_execution": False,
        }
    }
    verdict: dict = {}

    pipeline._apply_microboost_watch_entry_report(l12_verdict=verdict, report=report)

    assert verdict["microboost_watch_entry"]["signal_json_emit_result"] is False
    assert verdict["microboost_watch_entry"]["lifecycle_track"] is True
    assert tracker.tracked == []


def test_pipeline_records_counter_entry_emit_result():
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_lifecycle_manager = SignalLifecycleManager()
    emitted: list[dict] = []
    pipeline._emit_signal_json_payload = lambda payload: emitted.append(payload) or False

    class _Tracker:
        def __init__(self) -> None:
            self.tracked: list[dict] = []

        def track(self, payload: dict) -> None:
            self.tracked.append(payload)

    tracker = _Tracker()
    cast(Any, pipeline)._signal_block_finalizer = tracker
    report = {
        "microboost_counter_entry": {
            "symbol": "USDCAD",
            "cluster_id": "USDCAD_20260521T030620Z",
            "status": "SELL_ABSORPTION_WATCH",
            "signal_family": "MICROBOOST_COUNTER_ENTRY",
            "raw_direction": "BUY",
            "candidate_direction": "SELL",
            "validated_direction": None,
            "watch_direction": "SELL",
            "final_direction": "WAIT",
            "action": "WAIT_M15_CLOSE_CONFIRMATION",
            "signal_valid_time_utc": "2026-05-21T03:09:22+00:00",
            "signal_valid_price": 1.37633,
            "entry_reference_price": 1.37633,
            "entry_zone": [1.37633, 1.37647],
            "rr_status": "WATCH",
            "market_context_applied": True,
            "valid_for_execution": False,
            "requires_m15_close": True,
            "pending_decision_id": "USDCAD_20260521T030620Z_M15_DECISION",
        }
    }
    verdict: dict = {}

    pipeline._apply_microboost_counter_entry_report(l12_verdict=verdict, report=report)

    assert emitted
    assert report["microboost_counter_entry"]["signal_json_emit_result"] is False
    assert verdict["microboost_counter_entry"]["signal_json_emit_result"] is False
    assert verdict["final_direction"] == "WAIT"
    assert verdict["direction_source"] == "MICROBOOST_COUNTER_ENTRY_ABSORPTION_WATCH"
    assert tracker.tracked[0]["status"] == "SELL_ABSORPTION_WATCH"


def test_pipeline_logs_block_finalizer_update_as_signal_decision_update_json(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True)

    update = {
        "event": "signal_decision_update_json",
        "symbol": "USDCAD",
        "cluster_id": "USDCAD_20260521T030620Z",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "status": "WAIT_STRUCTURE_OR_NEXT_M15",
        "previous_status": "SELL_ABSORPTION_WATCH",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "validated_direction": None,
        "watch_direction": "SELL",
        "final_direction": "WAIT",
        "direction_validation_status": "WATCH_ONLY_PENDING_CONFIRMATION",
        "action": "WAIT_STRUCTURE_OR_NEXT_M15",
        "signal_valid_time_utc": "2026-05-21T03:09:22+00:00",
        "signal_valid_price": 1.37633,
        "entry_reference_price": 1.37633,
        "entry_zone": [1.37633, 1.37647],
        "rr_status": "WATCH",
        "target_mode": "PROVISIONAL_RR_FALLBACK",
        "market_context_applied": True,
        "valid_for_execution": False,
        "decision_update_trigger": "IDLE_AND_HARD_AGE_FINALIZER",
        "pending_decision_id": "USDCAD_20260521T030620Z_M15_DECISION",
        "reason": "Pressure block ended; structure target is still incomplete.",
    }

    finalizer = _StaticFinalizer(update)
    cast(Any, pipeline)._signal_block_finalizer = finalizer
    report: dict = {"symbol_activity": {}}
    verdict: dict = {}

    pipeline._apply_signal_block_finalizer(l12_verdict=verdict, report=report, market_contexts={})

    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert '"status":"WAIT_STRUCTURE_OR_NEXT_M15"' in caplog.text
    assert '"previous_status":"SELL_ABSORPTION_WATCH"' in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert verdict["final_direction"] == "WAIT"
    assert verdict["direction_source"] == "SIGNAL_BLOCK_FINALIZER_DECISION_UPDATE"
    assert finalizer.tracked[0]["status"] == "WAIT_STRUCTURE_OR_NEXT_M15"
    assert report["signal_block_finalizer_updates"][0]["signal_json_emit_result"] is True


def test_pipeline_logs_no_trade_pressure_as_decision_update_not_signal_json(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True)

    report = {
        "counts": {"total_events": 3, "pairs": {"USDCAD": 3}},
        "symbol_activity": {
            "USDCAD": {
                "latest_event_utc": "2026-06-08T08:49:17+00:00",
                "latest_block_effective_ticks": 3,
            }
        },
        "microboost_summary": {"count_total": 0},
    }
    verdict: dict[str, Any] = {"verdict": "NO_TRADE", "direction": "BUY"}
    market_contexts = {
        "USDCAD": MarketContext(
            symbol="USDCAD",
            raw_allowed_direction="BUY",
            bid=1.3763,
            ask=1.3765,
            price_at_signal_end=1.3764,
        )
    }

    pipeline._apply_no_trade_pressure_decision_update(
        symbol="USDCAD",
        l12_verdict=verdict,
        report=report,
        market_contexts=market_contexts,
    )

    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert '"status":"NO_TRADE_REASONED"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
    assert verdict["no_trade_pressure_decision_update"]["terminal_status"] == "NO_TRADE_REASONED"
    assert verdict["no_trade_pressure_decision_update"]["signal_json_emit_result"] is True
    assert verdict["no_trade_pressure_decision_update"]["pressure_event_count"] == 3
    assert verdict["no_trade_pressure_decision_update"]["pressure_level"] == "PRESSURE_CANARY"
    assert verdict["no_trade_pressure_decision_update"]["execution_block_reason"] == "NON_EXECUTE_VERDICT"


def test_pipeline_routes_no_trade_pressure_to_pressure_state_when_guard_enabled(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    monkeypatch.setenv("SIGNAL_DECISION_SOURCE_GUARD_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_STATE_JSON_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DECISION_BYPASS_DISABLED", "true")
    monkeypatch.setenv("SIGNAL_DECISION_REQUIRE_LIFECYCLE_ANCHOR", "true")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._last_no_trade_pressure_decision_at = {}

    report = {
        "counts": {"total_events": 3, "pairs": {"USDCAD": 3}},
        "symbol_activity": {
            "USDCAD": {
                "latest_event_utc": "2026-06-08T08:49:17+00:00",
                "latest_block_effective_ticks": 3,
            }
        },
        "microboost_summary": {"count_total": 0},
    }
    verdict: dict[str, Any] = {"verdict": "NO_TRADE", "direction": "BUY"}
    market_contexts = {
        "USDCAD": MarketContext(
            symbol="USDCAD",
            raw_allowed_direction="BUY",
            bid=1.3763,
            ask=1.3765,
            price_at_signal_end=1.3764,
        )
    }

    pipeline._apply_no_trade_pressure_decision_update(
        symbol="USDCAD",
        l12_verdict=verdict,
        report=report,
        market_contexts=market_contexts,
    )

    assert "[SignalPressureStateJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
    assert "no_trade_pressure_decision_update" not in verdict
    state = verdict["no_trade_pressure_state"]
    assert state["event"] == "signal_pressure_state_json"
    assert state["status"] == "PRESSURE_CANARY"
    assert state["eligible_for_signal_decision"] is False
    assert state["signal_pressure_state_emit_result"] is True


def test_pipeline_logs_allowed_quorum_context_gap_as_decision_update(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True)
    pipeline._last_allowed_quorum_decision_at = {}

    report = {
        "allowed_quorum": {
            "symbol": "AUDUSD",
            "direction": "BUY",
            "streak": 3,
            "quorum_size": 3,
            "quorum_reached": True,
        },
        "counts": {"total_events": 3, "pairs": {"AUDUSD": 3}},
        "symbol_activity": {
            "AUDUSD": {
                "latest_event_utc": "2026-06-09T02:01:28+00:00",
                "latest_block_effective_ticks": 3,
            }
        },
        "microboost_summary": {"count_total": 0},
        "watch_promotion_blockers": {
            "ALLOWED_QUORUM_PENDING_VALIDATION": 3,
            "MICROBOOST_NOT_FORMED": 3,
        },
    }
    verdict: dict[str, Any] = {
        "verdict": "EXECUTE_REDUCED_RISK_BUY",
        "direction": "BUY",
        "errors": ["L1_BLOCKER:LOW_CONTEXT_COHERENCE"],
    }
    market_contexts = {
        "AUDUSD": MarketContext(
            symbol="AUDUSD",
            raw_allowed_direction="BUY",
            bid=0.6612,
            ask=0.6613,
            price_at_signal_end=0.66125,
        )
    }

    pipeline._apply_allowed_quorum_decision_update(
        symbol="AUDUSD",
        synthesis={"execution": {"direction": "BUY", "entry_price": 0.66125}},
        l12_verdict=verdict,
        report=report,
        market_contexts=market_contexts,
        source_verdict="EXECUTE_REDUCED_RISK_BUY",
    )

    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert "Allowed quorum pressure reached SignalThrottle" not in caplog.text
    assert '"signal_family":"SIGNAL_THROTTLE_ALLOWED_QUORUM"' in caplog.text
    assert '"status":"NO_TRADE_REASONED"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
    update = verdict["allowed_quorum_decision_update"]
    assert update["terminal_status"] == "NO_TRADE_REASONED"
    assert update["pressure_source"] == "SIGNAL_THROTTLE"
    assert update["allowed_quorum_seen"] is True
    assert update["pair_eligible_for_analysis"] is True
    assert update["watch_promotion_blockers"]["LOW_CONTEXT_COHERENCE"] == 1
    assert update["signal_json_emit_result"] is True
    emitted = next(rec.message for rec in caplog.records if "[SignalDecisionUpdateJSON]" in rec.message)
    emitted_payload = json.loads(emitted.split("[SignalDecisionUpdateJSON]", 1)[1].strip())
    assert emitted_payload["pressure_source"] == "SIGNAL_THROTTLE"
    assert emitted_payload["pressure_level"] == "PRESSURE_CANARY"
    assert emitted_payload["allowed_quorum"] is True
    assert emitted_payload["allowed_quorum_streak"] == 3
    assert emitted_payload["allowed_quorum_context"]["quorum_reached"] is True
    assert emitted_payload["watch_promotion_blockers"]["LOW_CONTEXT_COHERENCE"] == 1
    assert emitted_payload["microboost_detected"] is False


def test_pipeline_routes_allowed_quorum_to_pressure_state_when_guard_enabled(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    monkeypatch.setenv("SIGNAL_DECISION_SOURCE_GUARD_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_STATE_JSON_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DECISION_BYPASS_DISABLED", "true")
    monkeypatch.setenv("SIGNAL_DECISION_REQUIRE_LIFECYCLE_ANCHOR", "true")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._last_allowed_quorum_decision_at = {}

    report = {
        "allowed_quorum": {
            "symbol": "AUDUSD",
            "direction": "BUY",
            "streak": 3,
            "quorum_size": 3,
            "quorum_reached": True,
        },
        "counts": {"total_events": 3, "pairs": {"AUDUSD": 3}},
        "symbol_activity": {
            "AUDUSD": {
                "latest_event_utc": "2026-06-09T02:01:28+00:00",
                "latest_block_effective_ticks": 3,
            }
        },
        "microboost_summary": {"count_total": 0},
        "watch_promotion_blockers": {
            "ALLOWED_QUORUM_PENDING_VALIDATION": 3,
            "MICROBOOST_NOT_FORMED": 3,
        },
    }
    verdict: dict[str, Any] = {
        "verdict": "EXECUTE_REDUCED_RISK_BUY",
        "direction": "BUY",
        "errors": ["L1_BLOCKER:LOW_CONTEXT_COHERENCE"],
    }
    market_contexts = {
        "AUDUSD": MarketContext(
            symbol="AUDUSD",
            raw_allowed_direction="BUY",
            bid=0.6612,
            ask=0.6613,
            price_at_signal_end=0.66125,
        )
    }

    pipeline._apply_allowed_quorum_decision_update(
        symbol="AUDUSD",
        synthesis={"execution": {"direction": "BUY", "entry_price": 0.66125}},
        l12_verdict=verdict,
        report=report,
        market_contexts=market_contexts,
        source_verdict="EXECUTE_REDUCED_RISK_BUY",
    )

    assert "[SignalPressureStateJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
    assert "allowed_quorum_decision_update" not in verdict
    state = verdict["allowed_quorum_pressure_state"]
    assert state["status"] == "ALLOWED_QUORUM_WAIT_CONTEXT"
    assert state["source_stage"] == "SIGNAL_THROTTLE_INTEL"
    assert state["eligible_for_signal_decision"] is False
    assert state["signal_pressure_state_emit_result"] is True


def test_pipeline_suppresses_single_no_trade_pressure_canary(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True)

    report = {
        "counts": {"total_events": 1, "pairs": {"USDCAD": 1}},
        "symbol_activity": {
            "USDCAD": {
                "latest_event_utc": "2026-06-08T08:49:17+00:00",
                "latest_block_effective_ticks": 1,
            }
        },
        "microboost_summary": {"count_total": 0},
    }
    verdict: dict[str, Any] = {"verdict": "NO_TRADE", "direction": "BUY"}
    market_contexts = {
        "USDCAD": MarketContext(
            symbol="USDCAD",
            raw_allowed_direction="BUY",
            bid=1.3763,
            ask=1.3765,
            price_at_signal_end=1.3764,
        )
    }

    pipeline._apply_no_trade_pressure_decision_update(
        symbol="USDCAD",
        l12_verdict=verdict,
        report=report,
        market_contexts=market_contexts,
    )

    assert "no_trade_pressure_decision_update" not in verdict
    assert "[SignalDecisionUpdateJSON]" not in caplog.text


def test_pipeline_logs_block_finalizer_final_as_signal_json(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_lifecycle_manager = SignalLifecycleManager()
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True)
    finalizer = _StaticFinalizer(_finalizer_final_sell_payload())
    cast(Any, pipeline)._signal_block_finalizer = finalizer
    report: dict = {"symbol_activity": {}}
    verdict: dict = {}

    pipeline._apply_signal_block_finalizer(l12_verdict=verdict, report=report, market_contexts={})

    assert "[SignalJSON]" in caplog.text
    assert '"status":"FINAL_EXECUTION_READY"' in caplog.text
    assert '"source_status":"SELL_TIMING_VALID"' in caplog.text
    assert '"execution_valid_now":true' in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
    assert verdict["final_direction"] == "SELL"
    assert verdict["direction_source"] == "SIGNAL_BLOCK_FINALIZER"
    assert report["signal_block_finalizer_updates"][0]["status"] == "SELL_TIMING_VALID"
    assert report["signal_block_finalizer_updates"][0]["signal_json_emit_result"] is True
    assert finalizer.tracked[0]["status"] == "SELL_TIMING_VALID"
