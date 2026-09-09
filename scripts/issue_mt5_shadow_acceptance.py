"""Issue one signed, broker-forbidden MT5 SHADOW acceptance run."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from execution.mt5_command_repository import MT5CommandRepository
from execution.mt5_shadow_acceptance import (
    MAX_ACCEPTANCE_TTL_SECONDS,
    ShadowAcceptanceAuthorityV1,
    ShadowAcceptanceRequest,
)
from storage.postgres_client import pg_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-id", type=UUID, required=True)
    parser.add_argument("--acceptance-run-id", required=True)
    parser.add_argument("--phase", choices=("A1", "A2"), required=True)
    parser.add_argument("--ttl-seconds", type=int, default=300)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not 1 <= args.ttl_seconds <= MAX_ACCEPTANCE_TTL_SECONDS:
        parser.error(f"--ttl-seconds must be in [1, {MAX_ACCEPTANCE_TTL_SECONDS}]")
    if args.out.exists():
        parser.error("--out must not already exist")


async def issue(args: argparse.Namespace) -> dict[str, object]:
    issued_at = datetime.now(UTC)
    request = ShadowAcceptanceRequest(
        acceptance_run_id=args.acceptance_run_id,
        phase=args.phase,
        executor_id=args.executor_id,
        issued_at_utc=issued_at,
        expires_at_utc=issued_at + timedelta(seconds=args.ttl_seconds),
    )
    await pg_client.initialize()
    try:
        authority = ShadowAcceptanceAuthorityV1(MT5CommandRepository(pg=pg_client))
        return await authority.issue(request)
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
        print(f"SHADOW acceptance aborted: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"SHADOW acceptance queued manifest={args.out} phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
