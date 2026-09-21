"""Offline CLI: read a policy + captured bundle, write one JSON report.

Usage::

    python -m tools.shadow_harness.cli --policy POLICY.json --bundle BUNDLE.json --out REPORT.json

Reads local files only and writes exactly one new report file (never
overwrites). Exit codes: 0 gate passed, 1 gate failed, 2 input rejected.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.shadow_harness import HARNESS_VERSION
from tools.shadow_harness.evaluator import evaluate_bundle_bytes
from tools.shadow_harness.manifest import (
    HarnessInputError,
    load_policy,
    load_symbol_universe,
    resolve_symbol_map_path,
)

EXIT_GATE_PASSED = 0
EXIT_GATE_FAILED = 1
EXIT_INPUT_REJECTED = 2
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def run(policy_path: Path, bundle_path: Path, out_path: Path, repo_root: Path) -> int:
    try:
        loaded = load_policy(policy_path)
        universe = load_symbol_universe(resolve_symbol_map_path(loaded, repo_root), loaded)
        try:
            raw = bundle_path.read_bytes()
        except OSError as exc:
            raise HarnessInputError("BUNDLE_UNREADABLE", f"cannot read {bundle_path.name}") from exc
        report = evaluate_bundle_bytes(raw, loaded, universe)
    except HarnessInputError as exc:
        _write_new(
            out_path,
            {
                "report_schema": "wolf15.shadow-harness.report.v1",
                "harness_version": HARNESS_VERSION,
                "status": "INPUT_REJECTED",
                "gate_passed": False,
                "rejection_code": exc.code,
                "rejection_detail": exc.message,
            },
        )
        return EXIT_INPUT_REJECTED
    _write_new(out_path, report.to_json_dict())
    return EXIT_GATE_PASSED if report.gate_passed else EXIT_GATE_FAILED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="root that the policy's repository-relative symbol_map_relpath resolves against",
    )
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"refusing to overwrite existing report {args.out}")
    return run(args.policy, args.bundle, args.out, args.repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
