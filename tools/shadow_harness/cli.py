"""Offline CLI: read a policy + captured bundle, write one JSON report.

Usage::

    python -m tools.shadow_harness.cli --policy POLICY.json --bundle BUNDLE.json --out REPORT.json
        [--r9-envelope R9_ENVELOPE.json --r9-artifact R9_ARTIFACT]

Reads local files only and writes exactly one new report file (never
overwrites). Exit codes: 0 gate passed, 1 gate failed, 2 input rejected. The exit
code reflects the five-flag ``gate_passed`` only; exit 0 is NOT final SHADOW
acceptance - read ``shadow_acceptance_passed`` in the report for that.

At load the frozen R9 envelope schema document named by the policy is verified
against the policy pin (``R9_ENVELOPE_NOT_FROZEN`` / ``R9_ENVELOPE_PIN_MISMATCH``
reject the input). EXACT_S is accepted only by ``verify_r9_envelope_v1`` over the
supplied ``--r9-envelope`` JSON and ``--r9-artifact`` bytes; omitting either
means EXACT_S is never accepted.
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
    load_r9_envelope_pin,
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


def _optional_bytes(path: Path | None, code: str) -> bytes | None:
    if path is None:
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        raise HarnessInputError(code, f"cannot read {path.name}") from exc


def run(
    policy_path: Path,
    bundle_path: Path,
    out_path: Path,
    repo_root: Path,
    r9_envelope: Path | None,
    r9_artifact: Path | None,
) -> int:
    """``r9_envelope`` / ``r9_artifact`` are explicit; ``None`` means not supplied (exact-S cannot be accepted)."""

    try:
        loaded = load_policy(policy_path)
        universe = load_symbol_universe(resolve_symbol_map_path(loaded, repo_root), loaded)
        pin = load_r9_envelope_pin(loaded, repo_root)
        try:
            raw = bundle_path.read_bytes()
        except OSError as exc:
            raise HarnessInputError("BUNDLE_UNREADABLE", f"cannot read {bundle_path.name}") from exc
        report = evaluate_bundle_bytes(
            raw,
            loaded,
            universe,
            r9_envelope_pin=pin,
            r9_envelope=_optional_bytes(r9_envelope, "R9_ENVELOPE_UNREADABLE"),
            r9_artifact=_optional_bytes(r9_artifact, "R9_ARTIFACT_UNREADABLE"),
        )
    except HarnessInputError as exc:
        _write_new(
            out_path,
            {
                "report_schema": "wolf15.shadow-harness.report.v1",
                "harness_version": HARNESS_VERSION,
                "status": "INPUT_REJECTED",
                "gate_passed": False,
                "shadow_acceptance_passed": False,
                "rejection_code": exc.code,
                "rejection_detail": exc.message,
            },
        )
        return EXIT_INPUT_REJECTED
    _write_new(out_path, report.to_json_dict())
    return EXIT_GATE_PASSED if report.gate_passed else EXIT_GATE_FAILED


def _single(parser: argparse.ArgumentParser, values: list[Path] | None, flag: str) -> Path | None:
    if values is not None and len(values) > 1:
        parser.error(f"{flag} may be given at most once (one R9 envelope binds one R9 artifact)")
    return values[0] if values else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="root that the policy's repository-relative symbol_map_relpath and R9 schema document resolve against",
    )
    parser.add_argument(
        "--r9-envelope",
        type=Path,
        action="append",
        dest="r9_envelopes",
        help="R9EnvelopeV1 JSON file. Verified with --r9-artifact by verify_r9_envelope_v1, the only EXACT_S "
        "authority. Omitted = no envelope supplied, so exact-S is never accepted.",
    )
    parser.add_argument(
        "--r9-artifact",
        type=Path,
        action="append",
        dest="r9_artifacts",
        help="source R9 evidence artifact bytes whose sha256 the envelope's artifact_sha256 must equal. "
        "Omitted = ARTIFACT_BYTES_REQUIRED, so exact-S is never accepted.",
    )
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"refusing to overwrite existing report {args.out}")
    r9_envelope = _single(parser, args.r9_envelopes, "--r9-envelope")
    r9_artifact = _single(parser, args.r9_artifacts, "--r9-artifact")
    return run(args.policy, args.bundle, args.out, args.repo_root, r9_envelope, r9_artifact)


if __name__ == "__main__":
    raise SystemExit(main())
