from __future__ import annotations

import json
import logging
from typing import Any, cast

import pipeline.wolf_constitutional_pipeline as wolf_pipeline
from analysis.market_context_validator import MarketContext
from analysis.microboost_continuation_entry import MicroboostContinuationEngine
from analysis.signal_json_emitter import SignalJsonEmitter
from analysis.signal_json_gate_adapter import SignalJsonGateAdapter
from analysis.signal_lifecycle_manager import SignalLifecycleManager
from analysis.signal_throttle_pressure_tier import (
    TIER_1_PRIMARY_ANALYSIS,
    TIER_2_CONFIRMATION_SUPPORT,
    TIER_3_THEME_RADAR,
)
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


class _CandidateMarketContextBus:
    def get_latest_tick(self, symbol: str) -> dict[str, float]:
        if symbol.upper() == "AUDNZD":
            return {"bid": 1.0710, "ask": 1.0712}
        return {"bid": 1.0, "ask": 1.0002}

    def get_candle_history(self, symbol: str, timeframe: str, count: int = 1) -> list[dict[str, float]]:
        _ = symbol, timeframe
        candles: list[dict[str, float]] = []
        for index in range(max(count, 2)):
            close = 1.0780 - (index * 0.00015)
            open_ = close + 0.00005
            candles.append(
                {
                    "open": open_,
                    "high": max(open_, close) + 0.0008,
                    "low": min(open_, close) - 0.0008,
                    "close": close,
                }
            )
        return candles[-count:]


class _CandidateHydrationAnalyzer:
    def __init__(self) -> None:
        self.snapshot_context_symbols: list[list[str]] = []

    def snapshot(self, *, market_contexts: dict[str, MarketContext]) -> dict[str, Any]:
        self.snapshot_context_symbols.append(sorted(market_contexts))
        candidate: dict[str, Any] = {
            "symbol": "AUDNZD",
            "clean_block_direction": "SELL",
            "clean_block_duration_seconds": 7186.446,
            "effective_ticks": 120,
        }
        context = market_contexts.get("AUDNZD")
        if context is not None:
            candidate["market_context_snapshot"] = {"price_at_signal_end": context.price_at_signal_end}
        return {
            "clean_watch_candidates": [candidate],
            "pressure_tiers": [{"symbol": "AUDNZD", "tier_score": 100.0}],
        }


def test_pipeline_hydrates_market_context_for_global_signal_throttle_candidate(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_MAX_SYMBOLS", "4")
    monkeypatch.setenv("HTF_DAILY_PHASE_FEED_ENABLED", "false")
    monkeypatch.setenv("SIGNAL_BASKET_DIRECTION_VALIDATION_ENABLED", "false")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    cast(Any, pipeline)._context_bus = _CandidateMarketContextBus()

    report: dict[str, Any] = {
        "clean_watch_candidates": [
            {
                "symbol": "AUDNZD",
                "clean_block_direction": "SELL",
                "clean_block_duration_seconds": 7186.446,
                "effective_ticks": 120,
            }
        ],
        "pressure_tiers": [{"symbol": "AUDNZD", "tier_score": 100.0}],
    }
    market_contexts: dict[str, MarketContext] = {}

    hydration = pipeline._hydrate_signal_throttle_candidate_market_contexts(
        report=report,
        market_contexts=market_contexts,
        synthesis={"execution": {"entry_price": 9.9999}},
        l12_verdict={"verdict": "HOLD", "direction": None},
    )

    assert hydration["enabled"] is True
    assert hydration["advisory_only"] is True
    assert hydration["execution_impact"] is False
    assert hydration["snapshot_rebuild_required"] is True
    assert hydration["hydrated_symbols"] == ["AUDNZD"]
    assert "AUDNZD" in market_contexts
    context = market_contexts["AUDNZD"]
    assert context.raw_allowed_direction == "SELL"
    assert round(context.price_at_signal_end or 0.0, 4) == 1.0711
    assert context.price_at_signal_start != 9.9999
    assert context.price_position in {"MAIN_SUPPORT", "MID_RANGE", "MAIN_RESISTANCE"}


def test_signal_throttle_snapshot_rebuilds_after_candidate_context_hydration(monkeypatch):
    monkeypatch.setenv("SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_MAX_SYMBOLS", "4")
    monkeypatch.setenv("HTF_DAILY_PHASE_FEED_ENABLED", "false")
    monkeypatch.setenv("SIGNAL_BASKET_DIRECTION_VALIDATION_ENABLED", "false")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    analyzer = _CandidateHydrationAnalyzer()
    cast(Any, pipeline)._context_bus = _CandidateMarketContextBus()
    cast(Any, pipeline)._signal_throttle_live_analyzer = analyzer
    cast(Any, pipeline)._signal_throttle_market_contexts = lambda **_: {
        "EURUSD": MarketContext(symbol="EURUSD", raw_allowed_direction="BUY", price_at_signal_end=1.0)
    }
    cast(Any, pipeline)._emit_signal_throttle_fusion_v3_diagnostic = lambda _report: None
    cast(Any, pipeline)._emit_signal_throttle_pressure_tier_snapshot = lambda _report: None
    cast(Any, pipeline)._apply_microboost_continuation_entry_report = lambda **_: None
    cast(Any, pipeline)._apply_microboost_counter_entry_report = lambda **_: None
    cast(Any, pipeline)._apply_microboost_watch_entry_report = lambda **_: None
    cast(Any, pipeline)._apply_clean_block_watch_routes = lambda **_: None
    cast(Any, pipeline)._apply_signal_block_finalizer = lambda **_: None
    cast(Any, pipeline)._apply_allowed_quorum_decision_update = lambda **_: None
    cast(Any, pipeline)._emit_microboost_intel_if_new = lambda _report: None
    cast(Any, pipeline)._emit_signal_throttle_state_snapshot = lambda _report: None
    cast(Any, pipeline).family_counters_snapshot = lambda: {}

    report = pipeline._process_signal_throttle_snapshot(
        symbol="EURUSD",
        synthesis={"execution": {"entry_price": 9.9999}},
        l12_verdict={"verdict": "HOLD", "direction": None},
        source_verdict="HOLD",
    )

    assert analyzer.snapshot_context_symbols == [["EURUSD"], ["AUDNZD", "EURUSD"]]
    hydration = report["candidate_market_context_hydration"]
    assert hydration["hydrated_symbols"] == ["AUDNZD"]
    assert hydration["execution_impact"] is False
    assert report["clean_watch_candidates"][0]["market_context_snapshot"]["price_at_signal_end"] is not None


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
            "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
            "source_clean_block_confirmed": True,
            "source_clean_block_id": "CADJPY_20260518T133000Z_20260518T133229Z",
            "source_pressure_block_id": "CADJPY_20260518T133000Z_20260518T133229Z",
            "clean_block_valid": True,
            "clean_block_direction": "BUY",
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
    assert verdict["microboost_watch_entry"]["pending_decision_id"] == "CADJPY_20260518T133000Z_M15_DECISION"
    assert "CADJPY_CADJPY" not in verdict["microboost_watch_entry"]["pending_decision_id"]


def test_pipeline_attaches_pressure_priority_context_to_signal_watch(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True, emit_watch=True)

    report = {
        "pressure_tier_snapshot": {
            "symbols": [
                {
                    "symbol": "CADJPY",
                    "direction": "BUY",
                    "effective_pressure_tier": TIER_1_PRIMARY_ANALYSIS,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 88.0,
                    "tier_action": "PRIORITIZE_ANALYSIS",
                    "tier_reasons": ["RECENT_CLEAN_BLOCK_GE_5M"],
                    "metrics": {"live": {"event_count": 7}},
                }
            ]
        },
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
            "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
            "source_clean_block_confirmed": True,
            "source_clean_block_id": "CADJPY_20260518T133000Z_20260518T133229Z",
            "source_pressure_block_id": "CADJPY_20260518T133000Z_20260518T133229Z",
            "clean_block_valid": True,
            "clean_block_direction": "BUY",
        },
    }
    verdict: dict = {}

    pipeline._apply_microboost_watch_entry_report(l12_verdict=verdict, report=report)

    context = verdict["microboost_watch_entry"]["pressure_priority_context"]
    assert context["effective_pressure_tier"] == TIER_1_PRIMARY_ANALYSIS
    assert context["tier_source_event"] == "SignalThrottlePressureTierSnapshot"
    assert context["tier_execution_impact"] is False
    assert '"pressure_priority_context":' in caplog.text
    assert '"signal_watch_pressure_tier":"TIER_1_PRIMARY_ANALYSIS"' in caplog.text
    assert '"signal_watch_priority_bucket":"PRIMARY_ANALYSIS"' in caplog.text
    assert '"signal_watch_tier_action":"PRIORITIZE_ANALYSIS"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text


def test_pipeline_attaches_tier3_key_level_exception_only_at_key_level(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._signal_json_gate_adapter = SignalJsonGateAdapter.from_env({})
    pipeline._signal_json_emitter = SignalJsonEmitter(enabled=True, emit_watch=True)

    report = {
        "pressure_tier_snapshot": {
            "symbols": [
                {
                    "symbol": "EURUSD",
                    "direction": "SELL",
                    "effective_pressure_tier": TIER_3_THEME_RADAR,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 28.0,
                    "tier_action": "RADAR_ONLY",
                    "tier_reasons": ["LOW_ACTIVITY"],
                    "metrics": {"live": {"event_count": 3}},
                }
            ]
        },
        "microboost_watch_entry": {
            "symbol": "EURUSD",
            "cluster_id": "EURUSD_20260518T133000Z",
            "signal_family": "MICROBOOST_WATCH",
            "status": "EARLY_SELL_WATCH",
            "raw_direction": "BUY",
            "candidate_direction": "SELL",
            "validated_direction": None,
            "watch_direction": "SELL",
            "final_direction": "WAIT",
            "action": "WAIT_REJECTION_OR_BREAKOUT_CONFIRMATION",
            "signal_valid_time_utc": "2026-05-18T13:32:29+00:00",
            "signal_valid_price": 1.0801,
            "entry_reference_price": 1.0801,
            "entry_zone": [1.0801, 1.0801],
            "price_position": "MAIN_RESISTANCE",
            "phase_priced": "RESISTANCE_PRESSURE_WARNING",
            "rr_status": "WATCH",
            "market_context_applied": True,
            "valid_for_execution": False,
            "reason": "low-event key-level watch",
            "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
            "source_clean_block_confirmed": True,
            "source_clean_block_id": "EURUSD_20260518T133000Z_20260518T133229Z",
            "source_pressure_block_id": "EURUSD_20260518T133000Z_20260518T133229Z",
            "clean_block_valid": True,
            "clean_block_direction": "SELL",
        },
    }
    verdict: dict = {}

    pipeline._apply_microboost_watch_entry_report(l12_verdict=verdict, report=report)

    context = verdict["microboost_watch_entry"]["pressure_priority_context"]
    assert context["effective_pressure_tier"] == "TIER_3_KEY_LEVEL_RADAR_EXCEPTION"
    assert context["tier_action"] == "RADAR_EXCEPTION_ONLY"
    assert context["impact_tier"] == "IMPACT_TIER_1_KEY_LEVEL"
    assert context["low_event_high_impact_candidate"] is True
    assert '"TIER_3_KEY_LEVEL_RADAR_EXCEPTION"' in caplog.text
    assert '"signal_watch_priority_bucket":"KEY_LEVEL_RADAR_EXCEPTION"' in caplog.text


def test_pipeline_emits_pressure_tier_snapshot_log(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    report = {
        "pressure_tier_snapshot": {
            "generated_at_utc": "2026-07-01T00:06:00+00:00",
            "mixed_deployment": False,
            "deployment_ids": [],
            "summary": {
                "tier_1": 1,
                "tier_2": 0,
                "tier_3": 2,
                "fragmented_pressure_radar": 1,
                "pressure_memory_radar": 0,
                "theme_rotation_radar": 1,
                "stale_archive": 0,
                "unsafe_mixed_deployment": 0,
            },
            "symbols": [
                {
                    "symbol": "XAGUSD",
                    "direction": "SELL",
                    "effective_pressure_tier": TIER_1_PRIMARY_ANALYSIS,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 88.0,
                    "tier_action": "PRIORITIZE_ANALYSIS",
                }
            ],
        }
    }

    pipeline._emit_signal_throttle_pressure_tier_snapshot(report)

    observability_records = [record for record in caplog.records if record.name == "signal_throttle_observability"]
    signal_json_records = [record for record in caplog.records if record.name == "signal_json"]
    assert report["pressure_tier_snapshot_emit_result"] is True
    assert observability_records
    assert not any("SignalThrottlePressureTierSnapshot" in record.getMessage() for record in signal_json_records)
    assert "[SignalThrottlePressureTierSnapshot]" in caplog.text
    assert '"event":"signal_throttle_pressure_tier_snapshot"' in caplog.text
    assert '"tier_3_hidden_count":4' in caplog.text
    assert '"radar_breakdown":{"tier_3_theme_radar":2,"fragmented_pressure_radar":1,"pressure_memory_radar":0,"theme_rotation_radar":1}' in caplog.text
    assert '"display_line":"pressure_tiers tier1=1[XAGUSD:SELL:88.0] tier2=0[-] tier3_hidden=4 radar_breakdown[tier3=2 fragmented=1 memory=0 theme_rotation=1] stale=0 unsafe_mixed=0 execution_impact=false"' in caplog.text
    assert '"decision_update_tier_context_allowed":false' in caplog.text


def test_pipeline_emits_followthrough_score_log(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    report = {
        "followthrough_scores": [
            {
                "symbol": "XAGUSD",
                "direction": "SELL",
                "followthrough_score": 82,
                "followthrough_bucket": "HIGH_FOLLOWTHROUGH_CANDIDATE",
                "pressure_quality_bucket": "ACTIVE_CLEAN_PRESSURE",
                "duration_maturity_bucket": "MAJOR_30M",
                "microboost_role": "CONFIRMATION_OR_ACCELERATION",
                "directional_room_pips": 44.0,
                "gap_health": "HEALTHY",
                "late_move_penalty": 0.0,
                "gap_degradation_penalty": 0.0,
                "risk_flags": [],
            }
        ]
    }

    pipeline._emit_signal_throttle_followthrough_scores(report)

    observability_records = [record for record in caplog.records if record.name == "signal_throttle_observability"]
    signal_json_records = [record for record in caplog.records if record.name == "signal_json"]
    assert report["followthrough_score_emit_result"] is True
    assert observability_records
    assert not any("SignalThrottleFollowthroughScore" in record.getMessage() for record in signal_json_records)
    assert "[SignalThrottleFollowthroughScore]" in caplog.text
    assert '"event":"signal_throttle_followthrough_score_snapshot"' in caplog.text
    assert '"display_line":"followthrough_scores total=1 top=1[XAGUSD:SELL:82:HIGH_FOLLOWTHROUGH_CANDIDATE] execution_impact=false"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text


def test_pipeline_emits_fusion_v3_diagnostic_on_dedicated_logger(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")
    caplog.set_level(logging.WARNING, logger="signal_throttle_fusion_v3")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    report = {
        "signal_throttle_fusion_v3": {
            "event": "signal_throttle_fusion_v3",
            "status": "PURE_RADAR_ONLY",
            "block_type": "PURE_PRESSURE_BLOCK",
            "symbol": "USDJPY",
            "block_id": "USDJPY_20260430T031631Z_20260430T052757Z",
            "start_ts": "2026-04-30T03:16:31+00:00",
            "end_ts": "2026-04-30T05:27:57+00:00",
            "duration_minutes": 131.44,
            "event_count": 105,
            "density_per_minute": 0.8,
            "max_gap_seconds": 3775.56,
            "gap_split_applied": False,
            "split_rule": "PAIR_ROTATION_ONLY",
            "pure_pressure_score": 92.0,
            "heat_score": 38.0,
            "pressure_class": "LONG_CONTEXTUAL_RADAR",
            "raw_pressure_direction": None,
            "direction_status": "UNRESOLVED",
            "market_structure_status": "PENDING",
            "final_direction": "WAIT",
            "valid_for_execution": False,
            "next_stage": "SIGNAL_WATCH",
        }
    }

    pipeline._emit_signal_throttle_fusion_v3_diagnostic(report)

    fusion_records = [record for record in caplog.records if record.name == "signal_throttle_fusion_v3"]
    signal_json_records = [record for record in caplog.records if record.name == "signal_json"]
    observability_records = [record for record in caplog.records if record.name == "signal_throttle_observability"]
    assert report["signal_throttle_fusion_v3_emit_result"] is True
    assert fusion_records
    assert not any("SignalThrottleFusionV3" in record.getMessage() for record in signal_json_records)
    assert not any("SignalThrottleFusionV3" in record.getMessage() for record in observability_records)
    assert "[SignalThrottleFusionV3]" in caplog.text
    assert '"event":"signal_throttle_fusion_v3"' in caplog.text
    assert '"gap_split_applied":false' in caplog.text
    assert '"valid_for_execution":false' in caplog.text


def test_pipeline_pressure_tier_snapshot_log_respects_max_symbols_env(caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_TIER_SNAPSHOT_MAX_SYMBOLS_PER_TIER", "1")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    report = {
        "pressure_tier_snapshot": {
            "generated_at_utc": "2026-07-01T00:06:00+00:00",
            "mixed_deployment": False,
            "deployment_ids": [],
            "summary": {
                "tier_1": 2,
                "tier_2": 2,
                "tier_3": 0,
                "stale_archive": 0,
                "unsafe_mixed_deployment": 0,
            },
            "symbols": [
                {
                    "symbol": "XAGUSD",
                    "direction": "SELL",
                    "effective_pressure_tier": TIER_1_PRIMARY_ANALYSIS,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 88.0,
                    "tier_action": "PRIORITIZE_ANALYSIS",
                },
                {
                    "symbol": "USDCAD",
                    "direction": "BUY",
                    "effective_pressure_tier": TIER_1_PRIMARY_ANALYSIS,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 82.0,
                    "tier_action": "PRIORITIZE_ANALYSIS",
                },
                {
                    "symbol": "AUDCAD",
                    "direction": "BUY",
                    "effective_pressure_tier": TIER_2_CONFIRMATION_SUPPORT,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 51.0,
                    "tier_action": "CONFIRMATION_SUPPORT",
                },
                {
                    "symbol": "EURUSD",
                    "direction": "SELL",
                    "effective_pressure_tier": TIER_2_CONFIRMATION_SUPPORT,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 49.0,
                    "tier_action": "CONFIRMATION_SUPPORT",
                },
            ],
        }
    }

    pipeline._emit_signal_throttle_pressure_tier_snapshot(report)

    payload_text = caplog.text
    assert '"tier_1":[{"symbol":"XAGUSD"' in payload_text
    assert '"tier_2":[{"symbol":"AUDCAD"' in payload_text
    assert '"symbol":"USDCAD"' not in payload_text
    assert '"symbol":"EURUSD"' not in payload_text


def test_pipeline_pressure_tier_snapshot_log_respects_interval_even_when_changed(caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")
    current_time = [1_000.0]
    monkeypatch.setattr(wolf_pipeline.time, "time", lambda: current_time[0])
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_TIER_SNAPSHOT_INTERVAL_SECONDS", "60")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)

    first_report = {
        "pressure_tier_snapshot": {
            "generated_at_utc": "2026-07-01T00:06:00+00:00",
            "mixed_deployment": False,
            "deployment_ids": [],
            "summary": {"tier_1": 1, "tier_2": 0, "tier_3": 0, "stale_archive": 0, "unsafe_mixed_deployment": 0},
            "symbols": [
                {
                    "symbol": "XAGUSD",
                    "direction": "SELL",
                    "effective_pressure_tier": TIER_1_PRIMARY_ANALYSIS,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 88.0,
                    "tier_action": "PRIORITIZE_ANALYSIS",
                }
            ],
        }
    }
    second_report = {
        "pressure_tier_snapshot": {
            "generated_at_utc": "2026-07-01T00:06:15+00:00",
            "mixed_deployment": False,
            "deployment_ids": [],
            "summary": {"tier_1": 1, "tier_2": 0, "tier_3": 0, "stale_archive": 0, "unsafe_mixed_deployment": 0},
            "symbols": [
                {
                    "symbol": "USDCAD",
                    "direction": "BUY",
                    "effective_pressure_tier": TIER_1_PRIMARY_ANALYSIS,
                    "tier_scope": "LIVE_120M",
                    "tier_score": 82.0,
                    "tier_action": "PRIORITIZE_ANALYSIS",
                }
            ],
        }
    }

    pipeline._emit_signal_throttle_pressure_tier_snapshot(first_report)
    current_time[0] += 15.0
    pipeline._emit_signal_throttle_pressure_tier_snapshot(second_report)

    emitted = [record for record in caplog.records if "SignalThrottlePressureTierSnapshot" in record.getMessage()]
    assert len(emitted) == 1
    assert first_report["pressure_tier_snapshot_emit_result"] is True
    assert second_report["pressure_tier_snapshot_emit_result"] is False
    assert second_report["pressure_tier_snapshot_emit_suppressed_reason"] == "RATE_LIMITED_WITHIN_INTERVAL"


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


def test_pipeline_emits_clean_block_radar_confirmed_event(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    monkeypatch.setenv("SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_ENABLED", "true")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    report = {
        "signal_watch_promotion_diagnostics": [
            {
                "event": "signal_throttle_clean_block_radar",
                "status": "CLEAN_BLOCK_CONFIRMED_RADAR",
                "symbol": "GBPNZD",
                "source_clean_block_id": "GBPNZD_20260623T060000Z_20260623T060500Z",
                "clean_block_valid": True,
                "eligible_for_signal_watch": False,
                "blocked_by": ["MARKET_CONTEXT_MISSING"],
                "next_required_stage": "PRICE_STRUCTURE_CONTEXT",
                "market_context_applied": False,
                "raw_signal_throttle_error_count": 7,
                "valid_for_execution": False,
                "is_final_signal": False,
                "final_direction": "WAIT",
            }
        ]
    }
    verdict: dict = {}

    pipeline._apply_clean_block_watch_routes(l12_verdict=verdict, report=report)

    assert "[SignalWatchPromotionDiagnostic]" in caplog.text
    assert '"event":"signal_throttle_clean_block_radar"' in caplog.text
    assert '"status":"CLEAN_BLOCK_CONFIRMED_RADAR"' in caplog.text
    assert '"raw_signal_throttle_error_count":7' in caplog.text
    assert report["signal_watch_promotion_diagnostics"][0]["diagnostic_emit_result"] is True
    assert verdict["signal_watch_promotion_diagnostics"][0]["next_required_stage"] == "PRICE_STRUCTURE_CONTEXT"


def test_pipeline_terminalizes_replayed_lineage_missing_watch_diagnostic(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    monkeypatch.setenv("SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_WATCH_LINEAGE_MISSING_TERMINAL_THRESHOLD", "2")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    payloads = [
        {
            "status": "MICROBOOST_WATCH",
            "signal_family": "MICROBOOST_WATCH",
            "cluster_id": "GBPJPY_20260707T144452Z",
            "symbol": "GBPJPY",
            "raw_direction": "SELL",
            "final_direction": "WAIT",
            "valid_for_execution": False,
        }
        for _ in range(4)
    ]

    results = [pipeline._emit_signal_json_payload(payload) for payload in payloads]

    emitted = [record for record in caplog.records if "SignalWatchPromotionDiagnostic" in record.getMessage()]
    assert results == [False, False, False, False]
    assert len(emitted) == 3
    assert '"lineage_missing_replay_count":1' in emitted[0].getMessage()
    assert '"lineage_missing_replay_count":2' in emitted[1].getMessage()
    assert '"status":"LINEAGE_MISSING_TERMINAL"' in emitted[2].getMessage()
    assert payloads[2]["signal_json_emit_blocked_by_source_guard_terminal"] is True
    assert payloads[3]["signal_watch_source_diagnostic_terminal_suppressed"] is True
    assert payloads[3]["signal_watch_source_diagnostic_emit_result"] is False


def test_pipeline_terminalizes_replayed_report_promotion_diagnostic(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    monkeypatch.setenv("SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_WATCH_LINEAGE_MISSING_TERMINAL_THRESHOLD", "2")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)

    reports = []
    for _ in range(4):
        report = {
            "v1_clean_block_ledger": [
                {
                    "symbol": "GBPJPY",
                    "source_clean_block_id": "GBPJPY_20260707T143900Z_20260707T144500Z",
                    "clean_block_valid": True,
                    "clean_block_end_utc": "2026-07-07T14:45:00+00:00",
                    "clean_block_duration_seconds": 360.0,
                    "raw_pressure_direction": "SELL",
                }
            ],
            "signal_watch_promotion_diagnostics": [
                {
                    "event": "signal_watch_promotion_diagnostic",
                    "symbol": "GBPJPY",
                    "source_clean_block_id": None,
                    "clean_block_valid": False,
                    "eligible_for_signal_watch": False,
                    "blocked_by": ["SOURCE_CLEAN_BLOCK_ID_MISSING"],
                    "next_required_stage": "ATTACH_CLEAN_BLOCK_LINEAGE",
                    "status": "MICROBOOST_WATCH",
                    "signal_family": "MICROBOOST_WATCH",
                    "cluster_id": "GBPJPY_20260707T144452Z",
                    "valid_for_execution": False,
                    "is_final_signal": False,
                    "final_direction": "WAIT",
                }
            ],
        }
        reports.append(report)
        pipeline._apply_clean_block_watch_routes(l12_verdict={}, report=report)

    emitted = [record for record in caplog.records if "SignalWatchPromotionDiagnostic" in record.getMessage()]
    assert len(emitted) == 3
    assert '"source_lookup_stage":"SIGNAL_THROTTLE_V1_CLEAN_BLOCK_LEDGER"' in emitted[0].getMessage()
    assert '"source_clean_block_id":"GBPJPY_20260707T143900Z_20260707T144500Z"' in emitted[0].getMessage()
    assert '"status":"LINEAGE_MISSING_TERMINAL"' in emitted[2].getMessage()
    assert reports[2]["signal_watch_promotion_diagnostics"][0]["signal_json_emit_blocked_by_source_guard_terminal"]
    assert reports[3]["signal_watch_promotion_diagnostics"][0]["signal_watch_source_diagnostic_terminal_suppressed"]
    assert reports[3]["signal_watch_promotion_diagnostics"][0]["diagnostic_emit_result"] is False


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


def test_pipeline_logs_no_trade_pressure_as_pressure_state_by_default(caplog):
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

    assert "[SignalPressureStateJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert '"status":"PRESSURE_CANARY"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
    state = verdict["no_trade_pressure_state"]
    assert state["terminal_status"] == "PRESSURE_ONLY"
    assert state["eligible_for_signal_decision"] is False
    assert state["pressure_event_count"] == 3
    assert state["pressure_level"] == "PRESSURE_CANARY"
    assert state["execution_block_reason"] == "NON_EXECUTE_VERDICT"


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


def test_pipeline_logs_allowed_quorum_context_gap_as_pressure_state_by_default(caplog):
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

    assert "[SignalPressureStateJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert "Allowed quorum pressure reached SignalThrottle" not in caplog.text
    assert '"signal_family":"SIGNAL_THROTTLE_ALLOWED_QUORUM"' in caplog.text
    assert '"status":"ALLOWED_QUORUM_WAIT_CONTEXT"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
    state = verdict["allowed_quorum_pressure_state"]
    assert state["terminal_status"] == "PRESSURE_ONLY"
    assert state["pressure_source"] == "SIGNAL_THROTTLE"
    assert state["allowed_quorum_seen"] is True
    assert state["pair_eligible_for_analysis"] is True
    assert state["watch_promotion_blockers"]["LOW_CONTEXT_COHERENCE"] == 1
    assert state["signal_pressure_state_emit_result"] is True
    emitted = next(rec.message for rec in caplog.records if "[SignalPressureStateJSON]" in rec.message)
    emitted_payload = json.loads(emitted.split("[SignalPressureStateJSON]", 1)[1].strip())
    assert emitted_payload["pressure_source"] == "SIGNAL_THROTTLE"
    assert emitted_payload["pressure_level"] == "PRESSURE_CANARY"
    assert emitted_payload["allowed_quorum"]["quorum_reached"] is True
    assert emitted_payload["allowed_quorum"]["streak"] == 3
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


def test_allowed_quorum_contextless_l1_blocker_emits_pressure_state(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    monkeypatch.setenv("SIGNAL_DECISION_SOURCE_GUARD_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_STATE_JSON_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DECISION_BYPASS_DISABLED", "true")
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
        "signal_watch_promotion_diagnostics": [
            {
                "event": "signal_throttle_clean_block_radar",
                "symbol": "AUDUSD",
                "status": "CLEAN_BLOCK_CONFIRMED_RADAR",
                "valid_for_execution": False,
            }
        ],
    }
    verdict: dict[str, Any] = {
        "verdict": "HOLD",
        "direction": "BUY",
        "errors": ["L1_BLOCKER:LOW_CONTEXT_COHERENCE"],
    }

    pipeline._apply_allowed_quorum_decision_update(
        symbol="AUDUSD",
        synthesis={"execution": {"direction": "BUY"}},
        l12_verdict=verdict,
        report=report,
        market_contexts={},
        source_verdict="HOLD",
    )

    assert "[SignalPressureStateJSON]" in caplog.text
    assert "[SignalQuorumDiagnosticJSON]" not in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
    assert "[SignalJSON]" not in caplog.text
    state = verdict["allowed_quorum_pressure_state"]
    assert state["event"] == "signal_pressure_state_json"
    assert state["status"] == "ALLOWED_QUORUM_WAIT_CONTEXT"
    assert state["source_verdict_is_execute"] is False
    assert state["context_missing"] is True
    assert state["valid_for_execution"] is False
    assert state["execution_valid_now"] is False
    assert state["is_final_signal"] is False
    assert state["watch_promotion_blockers"]["LOW_CONTEXT_COHERENCE"] == 1
    assert state["watch_promotion_blockers"]["MARKET_CONTEXT_MISSING"] == 1
    assert state["watch_promotion_blockers"]["REFERENCE_PRICE_MISSING"] == 1
    assert state["signal_pressure_state_emit_result"] is True


def test_no_trade_contextless_pressure_emits_pressure_state(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    monkeypatch.setenv("SIGNAL_DECISION_SOURCE_GUARD_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_STATE_JSON_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DECISION_BYPASS_DISABLED", "true")
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._last_no_trade_pressure_decision_at = {}

    report = {
        "counts": {"total_events": 4, "pairs": {"USDCAD": 4}},
        "symbol_activity": {
            "USDCAD": {
                "latest_event_utc": "2026-06-08T08:49:17+00:00",
                "latest_block_effective_ticks": 4,
            }
        },
        "microboost_summary": {"count_total": 0},
    }
    verdict: dict[str, Any] = {
        "verdict": "NO_TRADE",
        "direction": "BUY",
        "errors": ["L1_BLOCKER:LOW_CONTEXT_COHERENCE"],
    }

    pipeline._apply_no_trade_pressure_decision_update(
        symbol="USDCAD",
        l12_verdict=verdict,
        report=report,
        market_contexts={},
    )

    assert "[SignalPressureStateJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
    assert "[SignalJSON]" not in caplog.text
    state = verdict["no_trade_pressure_state"]
    assert state["event"] == "signal_pressure_state_json"
    assert state["status"] == "PRESSURE_CANARY"
    assert state["context_missing"] is True
    assert state["pressure_event_count"] == 4
    assert state["valid_for_execution"] is False
    assert state["execution_valid_now"] is False
    assert state["is_final_signal"] is False
    assert state["watch_promotion_blockers"]["LOW_CONTEXT_COHERENCE"] == 1
    assert state["watch_promotion_blockers"]["NON_EXECUTE_VERDICT"] == 1
    assert state["watch_promotion_blockers"]["MARKET_CONTEXT_MISSING"] == 1
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
