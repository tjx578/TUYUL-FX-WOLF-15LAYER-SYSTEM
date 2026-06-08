from __future__ import annotations

import logging
from typing import Any, cast

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
    assert finalizer.tracked[0]["status"] == "SELL_TIMING_VALID"
