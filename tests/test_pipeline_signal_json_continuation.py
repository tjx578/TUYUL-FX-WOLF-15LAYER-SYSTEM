from __future__ import annotations

import logging

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
