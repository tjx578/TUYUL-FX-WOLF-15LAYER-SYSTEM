"""Issue one operator-controlled, risk-authorized MT5 SHADOW command."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from contracts.mt5_operator_shadow import C3_MAX_REQUEST_TTL_SECONDS, OperatorShadowRequest
from execution.mt5_operator_shadow_wiring import OperatorControlledShadowAuthorityV1
from storage.postgres_client import pg_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-run-id", required=True)
    parser.add_argument("--confirm-run-id", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--tradeplan-id", required=True)
    parser.add_argument("--executor-id", type=UUID, required=True)
    parser.add_argument("--broker-symbol", required=True)
    parser.add_argument("--expected-governance-version", type=int, required=True)
    parser.add_argument("--ttl-seconds", type=int, default=120)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.operator_run_id != args.confirm_run_id:
        parser.error("--confirm-run-id must exactly match --operator-run-id")
    if not 1 <= args.ttl_seconds <= C3_MAX_REQUEST_TTL_SECONDS:
        parser.error(f"--ttl-seconds must be in [1, {C3_MAX_REQUEST_TTL_SECONDS}]")
    if args.expected_governance_version < 1:
        parser.error("--expected-governance-version must be positive")
    if args.out.exists():
        parser.error("--out must not already exist")


async def issue(args: argparse.Namespace) -> dict[str, object]:
    requested_at = datetime.now(UTC)
    request = OperatorShadowRequest(
        operator_run_id=args.operator_run_id,
        confirm_run_id=args.confirm_run_id,
        actor=args.actor,
        reason=args.reason,
        tradeplan_id=args.tradeplan_id,
        executor_id=args.executor_id,
        broker_symbol=args.broker_symbol,
        expected_governance_version=args.expected_governance_version,
        requested_at_utc=requested_at,
        expires_at_utc=requested_at + timedelta(seconds=args.ttl_seconds),
    )
    await pg_client.initialize()
    try:
        authority = OperatorControlledShadowAuthorityV1(pg=pg_client)
        manifest = await authority.issue(request)
        return manifest.model_dump(mode="json")
    finally:
        await pg_client.close()


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    try:
        manifest = asyncio.run(issue(args))
        _write_manifest(args.out, manifest)
    except Exception as exc:
        reason_code = str(getattr(exc, "reason_code", type(exc).__name__))
        print(f"C3 SHADOW command aborted: {reason_code}", file=sys.stderr)
        return 1
    print(f"C3 SHADOW command queued manifest={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
