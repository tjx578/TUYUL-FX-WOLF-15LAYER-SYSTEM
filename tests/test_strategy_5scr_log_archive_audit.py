from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.audit_strategy_5scr_log_archive import build_archive_audit


def _pressure_payload() -> dict[str, object]:
    return {
        "event": "signal_pressure_state_json",
        "schema_version": "1.0-pressure-state",
        "symbol": "CHFJPY",
        "cluster_id": "CHFJPY_20260717T130500Z_ALLOWED_QUORUM",
        "promotion_stage": "PRESSURE_ONLY",
        "raw_direction": "BUY",
        "final_direction": "WAIT",
        "signal_valid_time_utc": "2026-07-17T13:05:00+00:00",
        "signal_valid_price": 190.0,
        "entry_reference_price": 190.0,
        "price_source": "M15_CLOSE",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "pressure_seen": True,
        "pressure_event_count": 4,
        "pressure_level": "PRESSURE_CANARY",
        "pressure_strength": "CANARY",
        "allowed_quorum": {
            "symbol": "CHFJPY",
            "direction": "BUY",
            "streak": 3,
            "quorum_size": 3,
            "quorum_reached": True,
        },
        "htf_structure_context": {
            "daily_bias": "BEARISH",
            "h4_structure": "BEARISH_PULLBACK",
            "price_location": "H4_SUPPLY",
            "liquidity_context": "BUY_SIDE_LIQUIDITY_TEST",
            "allowed_playbook": "SELL_ON_REJECTION",
            "blocked_playbook": ["BUY_BREAKOUT_CHASE"],
        },
    }


def _record() -> dict[str, str]:
    message = json.dumps(_pressure_payload(), separators=(",", ":"))
    return {
        "message": f"WARNING signal_json [SignalPressureStateJSON] {message}",
        "timestamp": "2026-07-17T13:05:00.100Z",
    }


def test_archive_audit_deduplicates_the_same_event_across_overlapping_exports(
    tmp_path: Path,
) -> None:
    record = _record()
    (tmp_path / "logs.1.json").write_text(
        json.dumps([record]),
        encoding="utf-8",
    )
    with (tmp_path / "logs.2.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("message", "timestamp"))
        writer.writeheader()
        writer.writerow(record)

    result = build_archive_audit(tmp_path)
    summary = result["summary"]

    assert summary["scope"]["archive_files"] == 2
    assert summary["scope"]["files_with_pressure_marker"] == 2
    assert summary["pressure_events"]["parsed_occurrences_after_byte_file_dedup"] == 2
    assert summary["pressure_events"]["unique_events"] == 1
    assert summary["pressure_events"]["overlap_duplicate_occurrences"] == 1
    assert result["events"][0]["occurrences_across_exports"] == 2
    assert result["events"][0]["source_file_count"] == 2
    assert summary["tradeplan_validation"]["precision_denominator"] == 0


def test_archive_audit_skips_a_byte_identical_export(tmp_path: Path) -> None:
    content = json.dumps([_record()])
    (tmp_path / "logs.1.json").write_text(content, encoding="utf-8")
    (tmp_path / "logs.2.json").write_text(content, encoding="utf-8")

    result = build_archive_audit(tmp_path)
    summary = result["summary"]

    assert summary["scope"]["archive_files"] == 2
    assert summary["scope"]["byte_duplicate_files"] == 1
    assert summary["pressure_events"]["parsed_occurrences_after_byte_file_dedup"] == 1
    assert summary["pressure_events"]["unique_events"] == 1
