from __future__ import annotations

import argparse
import json
from pathlib import Path

from journal.forensic_replay import reconstruct_incident


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconstruct incident timeline from append-only forensic artifacts")
    parser.add_argument(
        "--correlation-id", required=True, help="Correlation ID (signal_id/take_id/execution_intent_id)"
    )
    parser.add_argument(
        "--artifact-log",
        default="storage/forensics/replay_artifacts.jsonl",
        help="Path to replay artifact JSONL",
    )
    parser.add_argument(
        "--audit-log",
        default="storage/audit/audit_trail.jsonl",
        help="Path to audit trail JSONL",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 2 when minimum replay artifacts are incomplete",
    )
    args = parser.parse_args()

    report = reconstruct_incident(
        args.correlation_id,
        artifact_log_path=Path(args.artifact_log),
        audit_log_path=Path(args.audit_log),
    )

    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))

    if args.strict and not bool(report.get("coverage", {}).get("is_sufficient")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
