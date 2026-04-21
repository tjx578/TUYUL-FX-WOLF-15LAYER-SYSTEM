#!/usr/bin/env python
"""Operator extractor for cached L2 MTA diagnostics.

Reads runtime verdict payloads and slim verdict meta from Redis and prints a
symbol-by-symbol summary of the existing L2 constitutional diagnostics.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_PASS = "[PASS]"
_WARN = "[WARN]"
_FAIL = "[FAIL]"
_INFO = "[INFO]"


def _load_json(raw: str | bytes | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _as_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _find_l2_summary(pair: str, redis_client: Any) -> dict[str, Any] | None:
    meta = _load_json(redis_client.get(f"L12:VERDICT_META:{pair}")) or {}
    summary = meta.get("l2_mta_summary")
    if isinstance(summary, dict):
        return summary

    verdict = _load_json(redis_client.get(f"L12:VERDICT:{pair}")) or {}
    diagnostics = verdict.get("mta_diagnostics")
    if not isinstance(diagnostics, dict):
        return None

    alignment_score = float(diagnostics.get("alignment_score") or 0.0)
    required_alignment = float(diagnostics.get("required_alignment") or 0.0)
    return {
        "alignment_score": alignment_score,
        "required_alignment": required_alignment,
        "alignment_gap": round(required_alignment - alignment_score, 4),
        "direction_consensus": diagnostics.get("direction_consensus"),
        "primary_conflict": diagnostics.get("primary_conflict"),
        "available_timeframes": _as_list(diagnostics.get("available_timeframes")),
        "missing_timeframes": _as_list(diagnostics.get("missing_timeframes")),
        "conflict_count": len(list(diagnostics.get("conflict_matrix") or [])),
    }


def main() -> int:
    from config_loader import load_pairs
    from storage.redis_client import redis_client

    try:
        redis_client.ping()
    except Exception as exc:
        print(f"{_FAIL} Redis connection failed: {exc}")
        return 1

    pairs = [str(p.get("symbol", "")).upper() for p in load_pairs() if p.get("enabled", True) and p.get("symbol")]
    print(f"{_INFO} L2 MTA diagnostics snapshot at {time.strftime('%Y-%m-%d %H:%M:%S')}")

    found = 0
    for pair in pairs:
        summary = _find_l2_summary(pair, redis_client)
        if summary is None:
            print(f"{_WARN} {pair}: no cached L2 diagnostics")
            continue

        found += 1
        missing = ",".join(_as_list(summary.get("missing_timeframes"))) or "-"
        available = ",".join(_as_list(summary.get("available_timeframes"))) or "-"
        print(
            f"{_PASS} {pair}: alignment={summary.get('alignment_score')} / {summary.get('required_alignment')} "
            f"gap={summary.get('alignment_gap')} consensus={summary.get('direction_consensus')} "
            f"conflict={summary.get('primary_conflict') or '-'} available={available} missing={missing}"
        )

    if found == 0:
        print(f"{_FAIL} No symbol had cached L2 diagnostics")
        return 1

    print(f"{_INFO} Found cached L2 diagnostics for {found}/{len(pairs)} symbol(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
