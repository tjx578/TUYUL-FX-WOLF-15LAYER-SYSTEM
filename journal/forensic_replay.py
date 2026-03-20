"""Append-only forensic replay artifacts for RCA reconstruction.

Zone: journal. This module has no decision authority and only records facts.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

FORENSIC_ARTIFACTS_PATH = Path("storage/forensics/replay_artifacts.jsonl")
AUDIT_TRAIL_PATH = Path("storage/audit/audit_trail.jsonl")

MINIMUM_REPLAY_ARTIFACTS: tuple[str, ...] = (
    "event_history",
    "verdict_provenance",
    "firewall_result",
    "execution_lifecycle",
    "freshness_snapshot",
)


def append_replay_artifact(
    artifact_type: str,
    *,
    correlation_id: str | None,
    payload: dict[str, Any],
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Append one immutable forensic artifact entry.

    The write path is append-only JSONL by design. Any failure is logged and
    should not affect caller flow.
    """
    target = log_path or FORENSIC_ARTIFACTS_PATH
    entry = {
        "artifact_id": f"rfa_{uuid.uuid4().hex[:16]}",
        "captured_at": datetime.now(UTC).isoformat(),
        "artifact_type": str(artifact_type),
        "correlation_id": (str(correlation_id).strip() if correlation_id else None),
        "payload": payload,
    }

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n")
            handle.flush()
    except Exception as exc:  # pragma: no cover - best effort path
        logger.warning("Forensic artifact append failed: {}", exc)

    return entry


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
    except Exception as exc:  # pragma: no cover - best effort path
        logger.warning("Forensic replay load failed for {}: {}", path, exc)
    return records


def load_replay_artifacts(*, log_path: Path | None = None) -> list[dict[str, Any]]:
    """Read immutable replay artifacts from JSONL store."""
    return _load_jsonl(log_path or FORENSIC_ARTIFACTS_PATH)


def load_audit_entries(*, log_path: Path | None = None) -> list[dict[str, Any]]:
    """Read append-only audit trail entries from JSONL store."""
    return _load_jsonl(log_path or AUDIT_TRAIL_PATH)


def _entry_ts(entry: dict[str, Any]) -> str:
    return str(entry.get("captured_at") or entry.get("timestamp") or "")


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in entries:
        key = json.dumps(item, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def reconstruct_incident(
    correlation_id: str,
    *,
    artifact_log_path: Path | None = None,
    audit_log_path: Path | None = None,
) -> dict[str, Any]:
    """Reconstruct an incident timeline from immutable forensic stores."""
    target = str(correlation_id).strip()
    if not target:
        raise ValueError("correlation_id is required")

    artifacts = load_replay_artifacts(log_path=artifact_log_path)
    matched = [a for a in artifacts if str(a.get("correlation_id") or "").strip() == target]

    by_type: dict[str, list[dict[str, Any]]] = {}
    for entry in matched:
        artifact_type = str(entry.get("artifact_type") or "unknown")
        by_type.setdefault(artifact_type, []).append(entry)

    audit_entries = load_audit_entries(log_path=audit_log_path)
    audit_related = [
        row
        for row in audit_entries
        if target
        in {
            str(row.get("resource") or ""),
            str((row.get("details") or {}).get("take_id") or ""),
            str((row.get("details") or {}).get("signal_id") or ""),
            str((row.get("details") or {}).get("execution_intent_id") or ""),
            str((row.get("details") or {}).get("trade_id") or ""),
        }
    ]

    timeline = _dedupe_entries(
        [
            {
                "timestamp": _entry_ts(a),
                "kind": "artifact",
                "artifact_type": a.get("artifact_type"),
                "correlation_id": a.get("correlation_id"),
                "payload": a.get("payload"),
            }
            for a in matched
        ]
        + [
            {
                "timestamp": str(row.get("timestamp") or ""),
                "kind": "audit",
                "action": row.get("action"),
                "resource": row.get("resource"),
                "details": row.get("details"),
            }
            for row in audit_related
        ]
    )
    timeline.sort(key=lambda item: str(item.get("timestamp") or ""))

    coverage = replay_coverage_report(matched)
    return {
        "correlation_id": target,
        "artifact_count": len(matched),
        "audit_count": len(audit_related),
        "artifacts_by_type": by_type,
        "coverage": coverage,
        "timeline": timeline,
    }


def replay_coverage_report(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Assess if minimum replay artifacts exist for an incident."""
    present = {str(e.get("artifact_type") or "") for e in entries}
    missing = [name for name in MINIMUM_REPLAY_ARTIFACTS if name not in present]
    return {
        "minimum_required": list(MINIMUM_REPLAY_ARTIFACTS),
        "present": sorted([p for p in present if p]),
        "missing": missing,
        "is_sufficient": len(missing) == 0,
    }
