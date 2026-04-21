#!/usr/bin/env python
"""
Shadow Journal Analyzer — P1 observation tool.

Reads the JSONL file produced by ``contracts.shadow_sink.ShadowJournalSink``
(default path: ``shadow_capture.jsonl``, overridable via
``WOLF_SHADOW_JOURNAL_PATH``) and emits an operator-readable summary:

  - Total records + time range
  - Per-symbol record counts
  - Envelope count stats (min / mean / max)
  - Projection failure rate (isolated per dual_emit, never impacts L12)
  - Build diagnostics (shadow bundle build failures)
  - Plane distribution across all captured envelopes
  - Top hard blockers across shadow bundles
  - Integrity notes (foreign signal ids, V11 leaks into planes)

**Read-only analysis.** This script never touches the live pipeline,
never mutates the journal file, and never makes network calls.

Usage::

    python scripts/analyze_shadow_journal.py
    python scripts/analyze_shadow_journal.py --path /var/log/wolf/shadow.jsonl
    python scripts/analyze_shadow_journal.py --json   # machine-readable

Exit codes:
    0  — analysis completed
    1  — file missing or unreadable
    2  — integrity violation detected (V11 in plane, foreign signal id)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

_DEFAULT_PATH = "shadow_capture.jsonl"
_PLANES = (
    "context_evidence",
    "alpha_evidence",
    "validation_evidence",
    "risk_evidence",
    "portfolio_evidence",
    "economics_evidence",
    "meta_evidence",
)
# Planes that L12 treats as decision-gating. ``meta_evidence`` is
# advisory per constitution; ``post_authority_veto`` is V11 (never
# appears in a correctly-built bundle but we filter defensively).
_BLOCKING_PLANES = (
    "context_evidence",
    "alpha_evidence",
    "validation_evidence",
    "risk_evidence",
    "portfolio_evidence",
    "economics_evidence",
)


def _iter_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                # Skip malformed lines — sink is append-only so partial
                # writes can happen in rare crash scenarios.
                continue


def analyze(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics over a sequence of journal records."""
    total = 0
    first_at: str | None = None
    last_at: str | None = None
    symbols: Counter[str] = Counter()
    envelope_counts: list[int] = []
    failure_counts: list[int] = []
    bundle_builds_ok = 0
    bundle_builds_failed = 0
    plane_layer_counts: Counter[str] = Counter()
    plane_counts: Counter[str] = Counter()
    hard_blockers: Counter[str] = Counter()
    integrity_issues: list[str] = []

    for rec in records:
        total += 1
        ts = rec.get("recorded_at")
        if isinstance(ts, str):
            if first_at is None or ts < first_at:
                first_at = ts
            if last_at is None or ts > last_at:
                last_at = ts

        summary = rec.get("summary") or {}
        symbol = str(summary.get("symbol", "UNKNOWN"))
        symbols[symbol] += 1
        envelope_counts.append(int(summary.get("envelope_count", 0) or 0))
        failure_counts.append(int(summary.get("failure_count", 0) or 0))
        if summary.get("build_diagnostics"):
            bundle_builds_failed += 1
        else:
            bundle_builds_ok += 1

        bundle = rec.get("bundle")
        if not isinstance(bundle, dict):
            continue

        expected_sid = summary.get("signal_id")
        actual_sid = bundle.get("signal_id")
        if expected_sid and actual_sid and expected_sid != actual_sid:
            integrity_issues.append(f"signal_id mismatch: summary={expected_sid!r} bundle={actual_sid!r}")

        for blocker in bundle.get("hard_blockers", []) or []:
            if isinstance(blocker, str):
                hard_blockers[blocker] += 1

        for plane in _PLANES:
            envs = bundle.get(plane) or []
            plane_counts[plane] += len(envs)
            for env in envs:
                if not isinstance(env, dict):
                    continue
                layer_id = env.get("layer_id")
                if layer_id == "V11":
                    integrity_issues.append(f"V11 envelope found in plane {plane!r} (should be filtered)")
                # LayerEnvelope v2 serializes the plane under the key ``plane``;
                # older fakes may use ``evidence_plane`` — accept both.
                env_plane = env.get("plane") or env.get("evidence_plane")
                if isinstance(env_plane, str):
                    plane_layer_counts[f"{env_plane}:{layer_id}"] += 1
                # Aggregate hard blockers from envelopes on blocking planes
                # (matches DecisionBundle.hard_blockers() semantics).
                if plane in _BLOCKING_PLANES:
                    # ``blockers`` is the canonical field name; tolerate
                    # ``blocker_codes`` as a legacy/fake alias.
                    codes = env.get("blockers") or env.get("blocker_codes") or []
                    for code in codes:
                        if isinstance(code, str):
                            hard_blockers[code] += 1

    env_stats: dict[str, float | int] = {}
    if envelope_counts:
        env_stats = {
            "min": min(envelope_counts),
            "max": max(envelope_counts),
            "mean": round(statistics.fmean(envelope_counts), 3),
            "median": int(statistics.median(envelope_counts)),
        }

    failure_rate = round(sum(1 for f in failure_counts if f > 0) / total, 4) if total > 0 else 0.0

    return {
        "total_records": total,
        "time_range": {"first": first_at, "last": last_at},
        "symbols": dict(symbols.most_common()),
        "envelope_counts": env_stats,
        "projection_failure_rate": failure_rate,
        "total_projection_failures": sum(failure_counts),
        "bundle_build": {
            "ok": bundle_builds_ok,
            "failed": bundle_builds_failed,
        },
        "plane_envelope_counts": dict(plane_counts),
        "plane_layer_breakdown": dict(plane_layer_counts.most_common()),
        "hard_blockers_top": dict(hard_blockers.most_common(10)),
        "integrity_issues": integrity_issues,
    }


def _format_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("═" * 68)
    lines.append("  SHADOW JOURNAL ANALYSIS")
    lines.append("═" * 68)
    lines.append(f"Total records       : {report['total_records']}")
    tr = report["time_range"]
    lines.append(f"Time range          : {tr.get('first')}  →  {tr.get('last')}")
    lines.append("")

    lines.append("── Symbols ─────────────────────────────────────────────")
    if report["symbols"]:
        for sym, n in report["symbols"].items():
            lines.append(f"  {sym:<12} {n}")
    else:
        lines.append("  (no records)")
    lines.append("")

    env = report["envelope_counts"]
    if env:
        lines.append("── Envelope counts per session ─────────────────────────")
        lines.append(f"  min={env['min']}  mean={env['mean']}  median={env['median']}  max={env['max']}")
        lines.append("")

    lines.append("── Projection failures (isolated, non-blocking) ────────")
    lines.append(f"  rate={report['projection_failure_rate'] * 100:.2f}%  total={report['total_projection_failures']}")
    lines.append("")

    bb = report["bundle_build"]
    lines.append("── Shadow bundle builds ────────────────────────────────")
    lines.append(f"  ok={bb['ok']}  failed={bb['failed']}")
    lines.append("")

    lines.append("── Plane envelope counts ───────────────────────────────")
    for plane in _PLANES:
        count = report["plane_envelope_counts"].get(plane, 0)
        lines.append(f"  {plane:<22} {count}")
    lines.append("")

    if report["hard_blockers_top"]:
        lines.append("── Top hard blockers (bundle-level) ────────────────────")
        for code, n in report["hard_blockers_top"].items():
            lines.append(f"  {code:<40} {n}")
        lines.append("")

    issues = report["integrity_issues"]
    if issues:
        lines.append("── INTEGRITY ISSUES (investigate) ──────────────────────")
        for msg in issues[:20]:
            lines.append(f"  ! {msg}")
        if len(issues) > 20:
            lines.append(f"  … {len(issues) - 20} more")
    else:
        lines.append("── Integrity ────────────────────────────────────────────")
        lines.append("  OK (no V11 leaks, no signal_id mismatches)")
    lines.append("═" * 68)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--path",
        default=os.getenv("WOLF_SHADOW_JOURNAL_PATH", _DEFAULT_PATH),
        help="Path to the shadow journal JSONL (default: $WOLF_SHADOW_JOURNAL_PATH or ./shadow_capture.jsonl)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON report instead of human-readable text",
    )
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"[FAIL] Journal file not found: {path}", file=sys.stderr)
        return 1
    try:
        report = analyze(_iter_records(path))
    except OSError as exc:
        print(f"[FAIL] Cannot read journal: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(_format_text(report))

    return 2 if report["integrity_issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
