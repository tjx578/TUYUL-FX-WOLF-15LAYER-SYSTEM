"""Queue or arm one default-off, broker-DEMO-only D0 engineering canary."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from execution.mt5_command_repository import MT5CommandRepository
from execution.mt5_engineering_demo_canary import (
    MAX_CANARY_TTL_SECONDS,
    EngineeringDemoCanaryAuthorityV1,
    EngineeringDemoCanaryRequest,
)
from execution.mt5_executor_governance import MT5ExecutorGovernanceRepository
from storage.postgres_client import pg_client

_ARM_CONFIRMATION = "ARM_ONE_ENGINEERING_DEMO_CANARY"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    queue = subparsers.add_parser("queue", help="queue while the global kill switch remains engaged")
    queue.add_argument("--canary-id", required=True)
    queue.add_argument("--executor-id", type=UUID, required=True)
    queue.add_argument("--account-id", required=True)
    queue.add_argument("--broker-server", required=True)
    queue.add_argument("--canonical-symbol", required=True)
    queue.add_argument("--broker-symbol", required=True)
    queue.add_argument("--account-snapshot-id", required=True)
    queue.add_argument("--side", choices=("BUY", "SELL"), required=True)
    queue.add_argument("--volume", type=float, required=True)
    queue.add_argument("--entry-price", type=float, required=True)
    queue.add_argument("--stop-loss", type=float, required=True)
    queue.add_argument("--take-profit", type=float, required=True)
    queue.add_argument("--max-spread-points", type=int, required=True)
    queue.add_argument("--max-price-drift-points", type=int, required=True)
    queue.add_argument("--ttl-seconds", type=int, default=90)
    queue.add_argument("--out", type=Path, required=True)

    arm = subparsers.add_parser("arm", help="open the exact one-shot scope and disengage delivery")
    arm.add_argument("--canary-id", required=True)
    arm.add_argument("--actor", required=True)
    arm.add_argument("--reason", required=True)
    arm.add_argument("--expected-governance-version", type=int, required=True)
    arm.add_argument("--confirm", required=True, help=f"must equal {_ARM_CONFIRMATION}")
    arm.add_argument("--out", type=Path, required=True)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.out.exists():
        parser.error("--out must not already exist")
    if args.operation == "queue" and not 1 <= args.ttl_seconds <= MAX_CANARY_TTL_SECONDS:
        parser.error(f"--ttl-seconds must be in [1, {MAX_CANARY_TTL_SECONDS}]")
    if args.operation == "arm" and args.confirm != _ARM_CONFIRMATION:
        parser.error(f"--confirm must equal {_ARM_CONFIRMATION}")


async def execute(args: argparse.Namespace) -> dict[str, object]:
    await pg_client.initialize()
    try:
        authority = EngineeringDemoCanaryAuthorityV1(MT5CommandRepository(pg=pg_client))
        if args.operation == "arm":
            return await authority.arm(
                args.canary_id,
                actor=args.actor,
                reason=args.reason,
                expected_governance_version=args.expected_governance_version,
            )
        issued_at = datetime.now(UTC)
        request = EngineeringDemoCanaryRequest(
            canary_id=args.canary_id,
            executor_id=args.executor_id,
            approved_account_id=args.account_id,
            approved_broker_server=args.broker_server,
            approved_canonical_symbol=args.canonical_symbol,
            approved_broker_symbol=args.broker_symbol,
            expected_account_snapshot_id=args.account_snapshot_id,
            side=args.side,
            volume=args.volume,
            entry_price=args.entry_price,
            stop_loss=args.stop_loss,
            take_profit=args.take_profit,
            max_spread_points=args.max_spread_points,
            max_price_drift_points=args.max_price_drift_points,
            issued_at_utc=issued_at,
            expires_at_utc=issued_at + timedelta(seconds=args.ttl_seconds),
        )
        return await authority.issue(request)
    finally:
        await pg_client.close()


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _preflight_manifest_path(path: Path) -> None:
    """Prove the evidence directory is writable before authority can commit."""

    path.parent.mkdir(parents=True, exist_ok=True)
    probe = path.with_name(path.name + ".preflight")
    created = False
    try:
        with probe.open("x", encoding="utf-8") as handle:
            created = True
            handle.write("D0_EVIDENCE_PREFLIGHT\n")
            handle.flush()
    finally:
        if created:
            probe.unlink(missing_ok=True)


def _manifest_sha256(manifest: dict[str, object]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


async def _contain_postcommit_failure(args: argparse.Namespace) -> str:
    if args.operation != "arm":
        return "KILL_SWITCH_ALREADY_ENGAGED"
    await pg_client.initialize()
    try:
        await MT5ExecutorGovernanceRepository(pg=pg_client).set_kill_switch(
            active=True,
            actor=f"{args.actor}:EVIDENCE_FAILURE",
            reason=f"D0 canary {args.canary_id} committed but local evidence write failed",
        )
    finally:
        await pg_client.close()
    return "KILL_SWITCH_REENGAGED"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    try:
        _preflight_manifest_path(args.out)
    except Exception as exc:
        print(f"Engineering DEMO canary not started: evidence preflight {type(exc).__name__}", file=sys.stderr)
        return 1
    try:
        manifest = asyncio.run(execute(args))
    except Exception as exc:
        print(f"Engineering DEMO canary aborted before commit: {type(exc).__name__}", file=sys.stderr)
        return 1
    try:
        _write_manifest(args.out, manifest)
    except Exception as exc:
        try:
            containment = asyncio.run(_contain_postcommit_failure(args))
        except Exception as containment_exc:
            containment = f"CONTAINMENT_FAILED_{type(containment_exc).__name__}"
        print(
            " ".join(
                (
                    f"ENGINEERING_DEMO_CANARY_{args.operation.upper()}_COMMITTED_EVIDENCE_WRITE_FAILED",
                    f"error={type(exc).__name__}",
                    f"manifest_sha256={_manifest_sha256(manifest)}",
                    f"canary_id={manifest.get('canary_id', args.canary_id)}",
                    f"command_id={manifest.get('command_id', 'UNKNOWN')}",
                    f"containment={containment}",
                )
            ),
            file=sys.stderr,
        )
        return 2
    print(f"Engineering DEMO canary {args.operation} evidence={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
