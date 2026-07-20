"""Replay Railway pressure logs through ``pressure_radar_gate_v1``."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from analysis.strategy_5scr_pressure_radar import (
    PressureRadarError,
    evaluate_pressure_radar,
    replay_pressure_radar_manifests,
)


def build_radar_replay_report(
    records: Sequence[Mapping[str, Any] | str],
    *,
    deployment_id: str,
) -> dict[str, Any]:
    evaluations = [evaluate_pressure_radar(record) for record in records]
    selected = [item for item in evaluations if item.deployment_id == deployment_id]
    if not selected:
        raise PressureRadarError("PRESSURE_RADAR_REPLAY_DEPLOYMENT_NOT_FOUND")
    manifests = replay_pressure_radar_manifests(records, deployment_id=deployment_id)
    qualifying = [item for item in selected if item.provisional_candidate]
    near = sorted({item.symbol for item in selected if item.reserve_near_qualified})
    return {
        "event": "pressure_radar_replay_report",
        "gate_rule_version": "pressure_radar_gate_v1",
        "deployment_id": deployment_id,
        "records_selected": len(selected),
        "symbols_observed": len({item.symbol for item in selected}),
        "qualifying_events": len(qualifying),
        "candidate_manifests": len(manifests),
        "analysis_ready_manifests": sum(item.status == "ANALYSIS_READY" for item in manifests),
        "directions": dict(sorted(Counter(item.raw_direction for item in qualifying).items())),
        "qualifying_stages": dict(sorted(Counter(item.qualifying_stage for item in qualifying).items())),
        "reserve_near_qualified_symbols": near,
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "is_final_signal": False,
        "manifests": [item.model_dump(mode="json") for item in manifests],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Railway JSON log export")
    parser.add_argument("--deployment-id", required=True, help="Exact deployment to replay")
    parser.add_argument("--output", type=Path, help="Optional output JSON path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise PressureRadarError("PRESSURE_RADAR_REPLAY_INPUT_NOT_LIST")
    records = [item for item in raw if isinstance(item, (dict, str))]
    report = build_radar_replay_report(records, deployment_id=args.deployment_id)
    serialized = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False)
    if args.output is None:
        print(serialized)
    else:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_radar_replay_report", "main"]
