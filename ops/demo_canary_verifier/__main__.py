"""Offline CLI: read exported evidence files, write one report. No network, DB, or broker access.

Usage::

    python -m ops.demo_canary_verifier envelope --bundle presubmit.json --out decision.json
    python -m ops.demo_canary_verifier reconcile --evidence chain.json --out report.json \
        [--ea-ledger-csv demo-ledger.csv] [--r9-envelope r9-envelope.json --r9-artifact r9-artifact.bin]

``--r9-envelope`` supplies the R9EnvelopeV1 JSON object (evidence ``r9_envelope``) and ``--r9-artifact`` the exact
R9 source artifact bytes (evidence ``r9_artifact_b64``, base64 of the file bytes); each may be supplied once.
Reports are written with exclusive create; an existing report is never overwritten.
Exit codes reuse ``ops.mt5_mcp.reconcile``: 0 pass, 2 not executed (missing evidence),
3 refused / not reconciled, 5 configuration error.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ops.demo_canary_verifier.chain import parse_ea_ledger_csv, reconcile_chain
from ops.demo_canary_verifier.envelope import EnvelopeError, check_presubmit_bundle, load_envelope
from ops.mt5_mcp.reconcile import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_EXECUTED_BLOCKED,
    EXIT_EXECUTED_INCOMPLETE,
    EXIT_EXECUTED_PASS,
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("EVIDENCE_NOT_OBJECT")
    return value


def _decode_ledger(raw: bytes) -> str:
    # MQL5 FILE_CSV without FILE_ANSI writes UTF-16LE with a BOM.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _write(path: Path, report: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ops.demo_canary_verifier")
    commands = parser.add_subparsers(dest="mode", required=True)
    envelope_cmd = commands.add_parser("envelope", help="check a pre-submit evidence bundle")
    envelope_cmd.add_argument("--bundle", type=Path, required=True)
    envelope_cmd.add_argument("--out", type=Path, required=True)
    reconcile_cmd = commands.add_parser("reconcile", help="reconcile an exported command chain")
    reconcile_cmd.add_argument("--evidence", type=Path, required=True)
    reconcile_cmd.add_argument("--ea-ledger-csv", type=Path)
    reconcile_cmd.add_argument("--r9-envelope", type=Path)
    reconcile_cmd.add_argument("--r9-artifact", type=Path)
    reconcile_cmd.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        envelope = load_envelope()
        if args.mode == "envelope":
            decision = check_presubmit_bundle(_read_json(args.bundle), envelope=envelope)
            _write(args.out, decision)
            return EXIT_EXECUTED_PASS if decision["status"] == "WITHIN_ENVELOPE" else EXIT_EXECUTED_BLOCKED
        evidence = _read_json(args.evidence)
        if args.ea_ledger_csv is not None:
            if evidence.get("ea_ledger") is not None:
                raise ValueError("EA_LEDGER_SUPPLIED_TWICE")
            evidence["ea_ledger"] = parse_ea_ledger_csv(_decode_ledger(args.ea_ledger_csv.read_bytes()))
        if args.r9_envelope is not None:
            if evidence.get("r9_envelope") is not None:
                raise ValueError("R9_ENVELOPE_SUPPLIED_TWICE")
            evidence["r9_envelope"] = _read_json(args.r9_envelope)
        if args.r9_artifact is not None:
            if evidence.get("r9_artifact_b64") is not None:
                raise ValueError("R9_ARTIFACT_SUPPLIED_TWICE")
            evidence["r9_artifact_b64"] = base64.b64encode(args.r9_artifact.read_bytes()).decode("ascii")
        report = reconcile_chain(evidence, envelope=envelope)
        _write(args.out, report)
    except (EnvelopeError, OSError, ValueError) as exc:
        print(f"demo_canary_verifier: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR
    if report["status"] == "RECONCILED":
        return EXIT_EXECUTED_PASS
    return EXIT_EXECUTED_INCOMPLETE if report["status"] == "NOT_EXECUTED" else EXIT_EXECUTED_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
