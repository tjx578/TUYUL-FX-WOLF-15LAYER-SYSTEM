"""Audit every Railway log export that can feed Strategy 5S-CR replay.

The archive may contain overlapping or byte-identical exports.  This command
therefore reports both raw occurrences and canonical pressure events, using the
same normalizer, SHA-256 event identity, lifecycle grouping, and pressure radar
gate as the runtime code.

This stage deliberately stops before closed-candle evidence.  A log record is
not market evidence and cannot be promoted to a tradeplan without an
authoritative as-of candle dataset.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson

from analysis.strategy_5scr_pressure_radar import (
    PressureRadarError,
    canonical_radar_payload,
    evaluate_pressure_radar,
    replay_pressure_radar_manifests,
)
from analysis.strategy_5scr_pressure_to_tradeplan import (
    PRESSURE_LOG_PREFIX,
    PressureEventNormalizer,
    PressureInputError,
    replay_pressure_records,
)

_MARKER = PRESSURE_LOG_PREFIX.encode("utf-8")
_CHUNK_SIZE = 4 * 1024 * 1024


def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _scan_file(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    marker_count = 0
    carry = b""
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
            marker_count += chunk.count(_MARKER)
            if carry:
                boundary = carry + chunk[: len(_MARKER) - 1]
                cursor = 0
                while True:
                    found = boundary.find(_MARKER, cursor)
                    if found < 0:
                        break
                    if found < len(carry) and found + len(_MARKER) > len(carry):
                        marker_count += 1
                    cursor = found + 1
            carry = chunk[-(len(_MARKER) - 1) :]
    stat = path.stat()
    return {
        "file_name": path.name,
        "extension": path.suffix.lower(),
        "bytes": stat.st_size,
        "modified_at_utc": _iso_utc(stat.st_mtime),
        "sha256": digest.hexdigest(),
        "pressure_marker_occurrences": marker_count,
    }


def _iter_json_records(path: Path) -> Iterator[Mapping[str, Any] | str]:
    payload = orjson.loads(path.read_bytes())
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, (dict, str)):
                yield item
        return
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            for item in records:
                if isinstance(item, (dict, str)):
                    yield item


def _iter_csv_records(path: Path) -> Iterator[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def _iter_records(path: Path) -> Iterator[Mapping[str, Any] | str]:
    if path.suffix.lower() == ".json":
        yield from _iter_json_records(path)
    elif path.suffix.lower() == ".csv":
        yield from _iter_csv_records(path)


def _message(record: Mapping[str, Any] | str) -> str:
    if isinstance(record, str):
        return record
    value = record.get("message")
    return value if isinstance(value, str) else ""


def _payload(record: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(record, Mapping) and str(record.get("event") or "").lower() == "signal_pressure_state_json":
        return dict(record)
    raw = _message(record)
    if PRESSURE_LOG_PREFIX in raw:
        raw = raw.split(PRESSURE_LOG_PREFIX, 1)[1].strip()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("pressure payload is not an object")
    return value


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], columns: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _event_row(
    event: Any,
    *,
    payload: Mapping[str, Any],
    occurrences: int,
    source_files: Iterable[str],
) -> dict[str, Any]:
    htf = event.htf_structure_context
    return {
        "event_id": event.event_id,
        "source_hash": event.source_hash,
        "symbol": event.symbol,
        "event_time_utc": event.event_time_utc.isoformat(),
        "deployment_id": payload.get("deployment_id"),
        "commit_sha": payload.get("commit_sha"),
        "cluster_id": event.cluster_id,
        "raw_direction": event.raw_direction,
        "pressure_event_count": event.pressure_event_count,
        "pressure_level": event.pressure_level,
        "pressure_strength": event.pressure_strength,
        "pair_eligible_for_analysis": event.pair_eligible_for_analysis,
        "allowed_quorum_reached": event.allowed_quorum_reached,
        "pressure_selection_confirmed": event.pressure_selection_confirmed,
        "source_clean_block_id": payload.get("source_clean_block_id"),
        "campaign_anchor_source": event.campaign_anchor_source,
        "campaign_anchor_execution_grade": event.campaign_anchor_execution_grade,
        "schema_version": event.schema_version,
        "daily_bias": htf.get("daily_bias"),
        "h4_structure": htf.get("h4_structure"),
        "price_location": htf.get("price_location"),
        "liquidity_context": htf.get("liquidity_context"),
        "liquidity_resolution": payload.get("liquidity_resolution"),
        "occurrences_across_exports": occurrences,
        "source_file_count": len(set(source_files)),
        "source_files": ";".join(sorted(set(source_files))),
    }


def _lifecycle_row(lifecycle: Any, *, lifecycle_kind: str) -> dict[str, Any]:
    return {
        "lifecycle_kind": lifecycle_kind,
        "campaign_id": lifecycle.campaign_id,
        "symbol": lifecycle.symbol,
        "raw_direction": lifecycle.raw_direction,
        "started_at_utc": lifecycle.started_at_utc.isoformat(),
        "updated_at_utc": lifecycle.updated_at_utc.isoformat(),
        "event_count": len(lifecycle.event_ids),
        "selected_by_pressure": lifecycle.selected_by_pressure,
        "max_reported_pressure_count": lifecycle.max_reported_pressure_count,
        "latest_pressure_level": lifecycle.latest_pressure_level,
        "campaign_anchor_source": lifecycle.campaign_anchor_source,
        "campaign_anchor_execution_grade": lifecycle.campaign_anchor_execution_grade,
        "legacy_grouping_rule_version": lifecycle.legacy_grouping_rule_version,
        "tradeplan_replay_status": "NOT_EVALUATED_CLOSED_CANDLES_REQUIRED",
    }


def build_archive_audit(input_dir: Path) -> dict[str, Any]:
    paths = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.name.startswith("logs.") and path.suffix.lower() in {".json", ".csv"}
    )
    manifest = [_scan_file(path) for path in paths]
    hashes: dict[str, list[str]] = defaultdict(list)
    for item in manifest:
        hashes[item["sha256"]].append(item["file_name"])
    for item in manifest:
        group = hashes[item["sha256"]]
        item["byte_duplicate_file_count"] = len(group)
        item["byte_duplicate_primary"] = sorted(group)[0]
        item["is_byte_duplicate"] = item["file_name"] != item["byte_duplicate_primary"]

    representative_paths = [
        input_dir / item["file_name"]
        for item in manifest
        if item["pressure_marker_occurrences"] > 0 and not item["is_byte_duplicate"]
    ]

    normalizer = PressureEventNormalizer(input_mode="REPLAY")
    events: dict[str, Any] = {}
    representative_records: dict[str, Mapping[str, Any] | str] = {}
    event_payloads: dict[str, dict[str, Any]] = {}
    event_sources: dict[str, set[str]] = defaultdict(set)
    event_occurrences: Counter[str] = Counter()
    normalization_errors: Counter[str] = Counter()
    parsed_pressure_occurrences = 0

    # Every non-byte-identical file is read so overlapping exports can be
    # measured at event grain.  Only the first record per event is retained.
    for path in representative_paths:
        try:
            records = _iter_records(path)
            for record in records:
                if PRESSURE_LOG_PREFIX not in _message(record):
                    continue
                parsed_pressure_occurrences += 1
                try:
                    event = normalizer.normalize(record)
                    payload = _payload(record)
                except (PressureInputError, ValueError, json.JSONDecodeError) as exc:
                    normalization_errors[str(exc)] += 1
                    continue
                event_occurrences[event.event_id] += 1
                event_sources[event.event_id].add(path.name)
                events.setdefault(event.event_id, event)
                representative_records.setdefault(event.event_id, record)
                event_payloads.setdefault(event.event_id, payload)
        except (csv.Error, OSError, orjson.JSONDecodeError) as exc:
            normalization_errors[f"FILE_READ_ERROR:{path.name}:{type(exc).__name__}"] += 1

    ordered_ids = sorted(events, key=lambda event_id: (events[event_id].event_time_utc, event_id))
    unique_records = [representative_records[event_id] for event_id in ordered_ids]
    raw_lifecycles = replay_pressure_records(unique_records) if unique_records else []

    deployment_ids = sorted(
        {
            str(event_payloads[event_id].get("deployment_id") or "").strip()
            for event_id in ordered_ids
            if str(event_payloads[event_id].get("deployment_id") or "").strip()
        }
    )
    radar_evaluations: dict[str, Any] = {}
    for event_id in ordered_ids:
        try:
            evaluation = evaluate_pressure_radar(representative_records[event_id])
            radar_evaluations[evaluation.event_id] = evaluation
        except PressureRadarError as exc:
            normalization_errors[f"RADAR:{exc}"] += 1

    manifests: list[Any] = []
    radar_errors: Counter[str] = Counter()
    for deployment_id in deployment_ids:
        try:
            manifests.extend(replay_pressure_radar_manifests(unique_records, deployment_id=deployment_id))
        except PressureRadarError as exc:
            radar_errors[str(exc)] += 1

    canonical_payloads: list[dict[str, Any]] = []
    for manifest_item in manifests:
        if manifest_item.status != "ANALYSIS_READY":
            continue
        evaluation = radar_evaluations.get(manifest_item.qualifying_event_id)
        if evaluation is None:
            radar_errors["QUALIFYING_EVENT_NOT_FOUND"] += 1
            continue
        payload = event_payloads.get(evaluation.event_id)
        if payload is None:
            radar_errors["QUALIFYING_PAYLOAD_NOT_FOUND"] += 1
            continue
        try:
            canonical_payloads.append(canonical_radar_payload(manifest_item, payload))
        except PressureRadarError as exc:
            radar_errors[str(exc)] += 1

    canonical_lifecycles = replay_pressure_records(canonical_payloads) if canonical_payloads else []
    event_rows = [
        _event_row(
            events[event_id],
            payload=event_payloads[event_id],
            occurrences=event_occurrences[event_id],
            source_files=event_sources[event_id],
        )
        for event_id in ordered_ids
    ]
    lifecycle_rows = [
        *(_lifecycle_row(item, lifecycle_kind="RAW_REPLAY") for item in raw_lifecycles),
        *(_lifecycle_row(item, lifecycle_kind="RADAR_CANONICAL") for item in canonical_lifecycles),
    ]
    manifest_rows = [
        {
            "manifest_id": item.manifest_id,
            "deployment_id": item.deployment_id,
            "symbol": item.symbol,
            "raw_direction": item.raw_direction,
            "status": item.status,
            "qualifying_time_utc": item.qualifying_time_utc.isoformat(),
            "lineage_finalized_at_utc": (
                item.lineage_finalized_at_utc.isoformat() if item.lineage_finalized_at_utc else None
            ),
            "qualifying_stage": item.qualifying_stage,
            "max_effective_ticks": item.max_effective_ticks,
            "source_clean_block_id": item.source_clean_block_id,
            "observed_event_count": len(item.observed_event_ids),
            "next_required_stage": item.next_required_stage,
            "tradeplan_replay_status": "NOT_EVALUATED_CLOSED_CANDLES_REQUIRED",
        }
        for item in manifests
    ]

    selected_lifecycles = [item for item in raw_lifecycles if item.selected_by_pressure]
    unique_event_count = len(events)
    duplicated_occurrences = max(0, parsed_pressure_occurrences - unique_event_count)
    first_event = events[ordered_ids[0]].event_time_utc.isoformat() if ordered_ids else None
    last_event = events[ordered_ids[-1]].event_time_utc.isoformat() if ordered_ids else None
    summary = {
        "event": "strategy_5scr_log_archive_audit",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scope": {
            "input_directory": input_dir.name,
            "file_pattern": "logs.*.{json,csv}",
            "archive_files": len(paths),
            "archive_bytes": sum(item["bytes"] for item in manifest),
            "archive_date_min_utc": min((item["modified_at_utc"] for item in manifest), default=None),
            "archive_date_max_utc": max((item["modified_at_utc"] for item in manifest), default=None),
            "files_with_pressure_marker": sum(item["pressure_marker_occurrences"] > 0 for item in manifest),
            "byte_duplicate_files": sum(item["is_byte_duplicate"] for item in manifest),
            "unique_file_hashes": len(hashes),
        },
        "pressure_events": {
            "parsed_occurrences_after_byte_file_dedup": parsed_pressure_occurrences,
            "unique_events": unique_event_count,
            "overlap_duplicate_occurrences": duplicated_occurrences,
            "overlap_duplicate_rate": (
                round(duplicated_occurrences / parsed_pressure_occurrences, 6) if parsed_pressure_occurrences else 0.0
            ),
            "normalization_errors": sum(normalization_errors.values()),
            "first_event_utc": first_event,
            "last_event_utc": last_event,
            "symbols": len({item.symbol for item in events.values()}),
            "deployments": len(deployment_ids),
            "canonical_lineage_events": sum(item.campaign_anchor_execution_grade for item in events.values()),
            "pressure_selected_events": sum(
                item.pair_eligible_for_analysis or item.allowed_quorum_reached or item.pressure_selection_confirmed
                for item in events.values()
            ),
        },
        "lifecycles": {
            "raw_replay": len(raw_lifecycles),
            "raw_pressure_selected": len(selected_lifecycles),
            "raw_execution_grade_anchor": sum(item.campaign_anchor_execution_grade for item in raw_lifecycles),
            "radar_manifests": len(manifests),
            "radar_manifest_statuses": dict(sorted(Counter(item.status for item in manifests).items())),
            "radar_analysis_ready": sum(item.status == "ANALYSIS_READY" for item in manifests),
            "radar_canonical_lifecycles": len(canonical_lifecycles),
        },
        "tradeplan_validation": {
            "closed_candle_dataset_attached": False,
            "tradeplans_evaluated": 0,
            "tradeplans_ready": 0,
            "m1_outcomes_classified": 0,
            "precision_denominator": 0,
            "status": "BLOCKED_AUTHORITATIVE_AS_OF_CANDLES_REQUIRED",
            "required_timeframes": ["D1", "H4", "H1", "M15", "M1"],
        },
        "distributions": {
            "symbols": dict(sorted(Counter(item.symbol for item in events.values()).items())),
            "deployments": dict(
                sorted(Counter(str(event_payloads[event_id].get("deployment_id")) for event_id in ordered_ids).items())
            ),
            "raw_directions": dict(
                sorted(Counter(item.raw_direction or "UNRESOLVED" for item in events.values()).items())
            ),
            "pressure_levels": dict(
                sorted(Counter(item.pressure_level or "MISSING" for item in events.values()).items())
            ),
        },
        "errors": {
            "normalization": dict(sorted(normalization_errors.items())),
            "radar": dict(sorted(radar_errors.items())),
        },
    }
    return {
        "summary": summary,
        "source_manifest": manifest,
        "events": event_rows,
        "lifecycles": lifecycle_rows,
        "radar_manifests": manifest_rows,
        "canonical_radar_payloads": canonical_payloads,
    }


def _write_outputs(result: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(result["summary"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        output_dir / "source_manifest.csv",
        result["source_manifest"],
        (
            "file_name",
            "extension",
            "bytes",
            "modified_at_utc",
            "sha256",
            "pressure_marker_occurrences",
            "byte_duplicate_file_count",
            "byte_duplicate_primary",
            "is_byte_duplicate",
        ),
    )
    _write_csv(
        output_dir / "unique_pressure_events.csv",
        result["events"],
        tuple(result["events"][0].keys()) if result["events"] else ("event_id",),
    )
    _write_csv(
        output_dir / "lifecycles.csv",
        result["lifecycles"],
        tuple(result["lifecycles"][0].keys()) if result["lifecycles"] else ("campaign_id",),
    )
    _write_csv(
        output_dir / "radar_manifests.csv",
        result["radar_manifests"],
        tuple(result["radar_manifests"][0].keys()) if result["radar_manifests"] else ("manifest_id",),
    )
    with (output_dir / "canonical_radar_payloads.jsonl").open("w", encoding="utf-8") as handle:
        for payload in result["canonical_radar_payloads"]:
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path, help="Directory containing logs.* JSON/CSV exports")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for reproducible audit outputs")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = build_archive_audit(args.input_dir)
    _write_outputs(result, args.output_dir)
    print(json.dumps(result["summary"], indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
