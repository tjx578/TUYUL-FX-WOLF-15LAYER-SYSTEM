from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from analysis.strategy_5scr_pressure_radar import (
    PressureRadarAssembler,
    canonical_radar_payload,
    evaluate_pressure_radar,
    parse_clean_block_interval,
    replay_pressure_radar_manifests,
)
from analysis.strategy_5scr_pressure_to_tradeplan import (
    PressureEventNormalizer,
    PressureInputError,
    PressureLifecycleAccumulator,
)
from services.pressure_outbox.radar_replay import build_radar_replay_report
from storage.pressure_outbox import prepare_pressure_event

START = datetime(2026, 7, 20, 6, 51, 23, tzinfo=UTC)


def _payload(
    symbol: str = "AUDUSD",
    *,
    deployment_id: str = "deployment-target",
    at: datetime = START,
    direction: str = "BUY",
    source_stage: str = "PRESSURE_BLOCK",
    signal_family: str = "SIGNAL_THROTTLE_PRESSURE",
    pair_eligible: bool | None = None,
    ticks: int = 3,
    clean_id: str | None = None,
    context_version: str = "pressure-context-v2:qualifying",
    daily_bias: str = "BULLISH",
    h4_structure: str = "BEARISH_PULLBACK",
    liquidity: str = "BUY_SIDE_APPROACHING",
    playbook: str = "WAIT_FOR_BUY_LOCATION",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": "signal_pressure_state_json",
        "schema_version": "2.0-pressure-state",
        "deployment_id": deployment_id,
        "cluster_id": f"{symbol}:{at.isoformat()}",
        "symbol": symbol,
        "raw_direction": direction,
        "signal_family": signal_family,
        "source_stage": source_stage,
        "promotion_stage": "PRESSURE_ONLY",
        "signal_valid_time_utc": at.isoformat(),
        "generated_at_utc": (at + timedelta(seconds=1)).isoformat(),
        "raw_direction_expires_at_utc": (at + timedelta(hours=4)).isoformat(),
        "raw_direction_eligible_for_context_resolution": True,
        "current_block_effective_ticks": ticks,
        "source_clean_block_id": clean_id,
        "context_version": context_version,
        "liquidity_resolution": liquidity,
        "direction_next_required_stage": "LIQUIDITY_ACCEPTANCE_OR_REJECTION",
        "next_required_stage": "MICROBOOST_OR_MARKET_CONTEXT",
        "htf_structure_context": {
            "daily_bias": daily_bias,
            "h4_structure": h4_structure,
            "price_location": "H4_SUPPLY",
            "liquidity_resolution": liquidity,
            "daily_bias_freshness_status": "FRESH",
            "allowed_playbook": playbook,
        },
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
    }
    if pair_eligible is not None:
        payload["pair_eligible_for_analysis"] = pair_eligible
    return payload


def _lineage_payload(qualifying: dict[str, Any], *, delay_seconds: int = 360) -> dict[str, Any]:
    at = datetime.fromisoformat(str(qualifying["signal_valid_time_utc"]))
    symbol = str(qualifying["symbol"])
    start = at.replace(microsecond=0)
    end = start + timedelta(minutes=5)
    clean_id = f"{symbol}_{start.strftime('%Y%m%dT%H%M%SZ')}_{end.strftime('%Y%m%dT%H%M%SZ')}"
    later = dict(qualifying)
    later.update(
        {
            "cluster_id": f"{symbol}:lineage",
            "signal_valid_time_utc": (at + timedelta(seconds=delay_seconds)).isoformat(),
            "generated_at_utc": (at + timedelta(seconds=delay_seconds + 1)).isoformat(),
            "source_stage": "SIGNAL_THROTTLE_INTEL",
            "signal_family": "SIGNAL_THROTTLE_PRESSURE",
            "current_block_effective_ticks": 1,
            "source_clean_block_id": clean_id,
            "context_version": "pressure-context-v2:lineage",
        }
    )
    later.pop("pair_eligible_for_analysis", None)
    return later


@pytest.mark.parametrize(
    ("source_stage", "signal_family", "pair_eligible", "expected_stage"),
    [
        ("PRESSURE_BLOCK", "SIGNAL_THROTTLE_PRESSURE", None, "PRESSURE_BLOCK"),
        ("CANDIDATE_LIFECYCLE", "SIGNAL_THROTTLE_PRESSURE", None, "CANDIDATE_LIFECYCLE"),
        ("SIGNAL_THROTTLE_INTEL", "SIGNAL_THROTTLE_ALLOWED_QUORUM", True, "ALLOWED_QUORUM"),
    ],
)
def test_gate_uses_exact_stage_and_direction_next_fields(
    source_stage: str,
    signal_family: str,
    pair_eligible: bool | None,
    expected_stage: str,
) -> None:
    payload = _payload(
        source_stage=source_stage,
        signal_family=signal_family,
        pair_eligible=pair_eligible,
    )
    payload["next_required_stage"] = "DELIBERATELY_NOT_THE_DIRECTION_FIELD"

    result = evaluate_pressure_radar(payload)

    assert result.provisional_candidate is True
    assert result.qualifying_stage == expected_stage
    assert result.failed_predicates == ()


def test_stage_only_failure_is_reserve_near_qualified() -> None:
    result = evaluate_pressure_radar(_payload(source_stage="SIGNAL_THROTTLE_INTEL"))

    assert result.provisional_candidate is False
    assert result.reserve_near_qualified is True
    assert result.failed_predicates == ("SOURCE_STAGE_NOT_ALLOWED",)


def test_assembler_latches_qualification_then_associates_later_lineage() -> None:
    qualifying = _payload()
    lineage = _lineage_payload(qualifying)
    assembler = PressureRadarAssembler()

    waiting = assembler.ingest(qualifying)
    ready = assembler.ingest(lineage)

    assert waiting.transition == "WAITING_CANONICAL_LINEAGE"
    assert waiting.manifest is not None
    assert waiting.manifest.source_clean_block_id is None
    assert ready.transition == "ANALYSIS_READY"
    assert ready.manifest is not None
    assert ready.manifest.status == "ANALYSIS_READY"
    assert ready.manifest.qualifying_stage == "PRESSURE_BLOCK"
    assert ready.manifest.max_effective_ticks == 3
    assert ready.manifest.context_version == "pressure-context-v2:qualifying"
    assert ready.manifest.lineage_context_version == "pressure-context-v2:lineage"
    assert ready.manifest.final_direction == "WAIT"
    assert ready.manifest.valid_for_execution is False
    assert ready.manifest.next_required_stage == "CLOSED_CANDLE_EVIDENCE"

    canonical = canonical_radar_payload(ready.manifest, qualifying)
    assert ready.manifest.lineage_finalized_at_utc is not None
    assert canonical["source_clean_block_id"] == lineage["source_clean_block_id"]
    assert canonical["qualifying_stage"] == "PRESSURE_BLOCK"
    assert canonical["current_block_effective_ticks"] == 3
    assert canonical["analysis_ready_at_utc"] == ready.manifest.lineage_finalized_at_utc.isoformat()
    assert canonical["lifecycle_anchor_at_utc"] == ready.manifest.qualifying_time_utc.isoformat()
    assert canonical["signal_valid_time_utc"] == ready.manifest.lineage_finalized_at_utc.isoformat()
    assert canonical["pressure_selection_confirmed"] is True
    assert canonical["lineage_context_version"] == "pressure-context-v2:lineage"
    assert canonical["final_direction"] == "WAIT"
    assert canonical["valid_for_execution"] is False
    prepared = prepare_pressure_event(canonical)
    assert prepared.source_clean_block_id == lineage["source_clean_block_id"]
    assert prepared.payload["radar_manifest_id"] == ready.manifest.manifest_id
    event = PressureEventNormalizer(input_mode="LIVE").normalize(prepared.payload)
    lifecycle = PressureLifecycleAccumulator().ingest(event)[0]
    assert event.pressure_selection_confirmed is True
    assert lifecycle.selected_by_pressure is True
    assert lifecycle.started_at_utc == ready.manifest.qualifying_time_utc
    assert lifecycle.updated_at_utc == ready.manifest.lineage_finalized_at_utc


def test_forged_selection_without_ready_radar_proof_is_rejected() -> None:
    payload = _payload(clean_id="AUDUSD_clean")
    payload["pressure_selection_confirmed"] = True

    with pytest.raises(PressureInputError, match="PRESSURE_SELECTION_PROOF_INVALID"):
        PressureEventNormalizer(input_mode="LIVE").normalize(payload)


def test_later_latest_row_cannot_erase_latched_ticks_or_stage() -> None:
    first = _payload(source_stage="PRESSURE_BLOCK", ticks=3)
    promoted = _payload(
        at=START + timedelta(seconds=10),
        source_stage="CANDIDATE_LIFECYCLE",
        ticks=5,
    )
    latest = _lineage_payload(first)
    assembler = PressureRadarAssembler()

    first_result = assembler.ingest(first)
    assembler.ingest(promoted)
    result = assembler.ingest(latest)

    assert first_result.manifest is not None
    assert result.manifest is not None
    assert result.manifest.manifest_id == first_result.manifest.manifest_id
    assert result.manifest.qualifying_event_id == first_result.evaluation.event_id
    assert result.manifest.qualifying_stage == "CANDIDATE_LIFECYCLE"
    assert result.manifest.max_effective_ticks == 5
    assert len(result.manifest.observed_event_ids) == 3


def test_context_mismatch_direction_reversal_and_expiry_fail_closed() -> None:
    qualifying = _payload()

    context_assembler = PressureRadarAssembler()
    context_assembler.ingest(qualifying)
    mismatch = _lineage_payload(qualifying)
    mismatch["htf_structure_context"] = {
        **mismatch["htf_structure_context"],
        "allowed_playbook": "WAIT_FOR_CONFIRMATION",
    }
    context_result = context_assembler.ingest(mismatch)
    assert context_result.transition == "RADAR_OBSERVED"
    assert context_assembler.snapshots()[0].status == "WAITING_CANONICAL_LINEAGE"

    reversal_assembler = PressureRadarAssembler()
    reversal_assembler.ingest(qualifying)
    reversal = _payload(at=START + timedelta(minutes=1), direction="SELL", ticks=1)
    reversal_result = reversal_assembler.ingest(reversal)
    assert reversal_result.transition == "RADAR_OBSERVED"
    assert reversal_assembler.snapshots()[0].status == "INVALIDATED_DIRECTION_REVERSAL"

    expiry_assembler = PressureRadarAssembler()
    expiry_assembler.ingest(qualifying)
    expiry_assembler.ingest(_lineage_payload(qualifying))
    assert expiry_assembler.snapshots()[0].status == "ANALYSIS_READY"
    expiry_assembler.advance_time(START + timedelta(hours=4, seconds=1))
    assert expiry_assembler.snapshots()[0].status == "EXPIRED"
    assert expiry_assembler.snapshots()[0].next_required_stage == "NONE"


def test_replay_is_deployment_scoped_and_report_is_non_executable() -> None:
    target = _payload(deployment_id="target")
    target_lineage = _lineage_payload(target)
    old = _payload(symbol="GBPUSD", deployment_id="old")
    old_lineage = _lineage_payload(old)
    records = [old, target_lineage, target, old_lineage]

    manifests = replay_pressure_radar_manifests(records, deployment_id="target")
    report = build_radar_replay_report(records, deployment_id="target")

    assert [item.symbol for item in manifests] == ["AUDUSD"]
    assert manifests[0].status == "ANALYSIS_READY"
    assert report["records_selected"] == 2
    assert report["candidate_manifests"] == 1
    assert report["analysis_ready_manifests"] == 1
    assert report["final_direction"] == "WAIT"
    assert report["valid_for_execution"] is False
    assert report["is_final_signal"] is False


def test_dedup_identity_is_scoped_by_deployment() -> None:
    target = _payload(deployment_id="target")
    old = {**target, "deployment_id": "old"}
    assembler = PressureRadarAssembler()

    old_result = assembler.ingest(old)
    target_result = assembler.ingest(target)
    duplicate = assembler.ingest(target)

    assert old_result.duplicate is False
    assert target_result.duplicate is False
    assert duplicate.duplicate is True
    assert {item.deployment_id for item in assembler.snapshots()} == {"old", "target"}


def test_clean_block_interval_is_symbol_scoped() -> None:
    source_id = "AUDUSD_20260720T065123Z_20260720T065623Z"

    assert parse_clean_block_interval(source_id, symbol="AUDUSD") == (
        datetime(2026, 7, 20, 6, 51, 23, tzinfo=UTC),
        datetime(2026, 7, 20, 6, 56, 23, tzinfo=UTC),
    )
    assert parse_clean_block_interval(source_id, symbol="GBPUSD") is None
