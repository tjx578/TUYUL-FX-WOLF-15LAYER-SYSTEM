"""Persist one pre-collected direct-MT5 reconciliation snapshot, fail closed."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from contracts.direct_broker_reconciliation import DirectBrokerReconciliationRequest
from execution.direct_broker_reconciliation_repository import (
    DirectBrokerReconciliationRepository,
    PostgresDirectBrokerReconciliationStore,
)
from storage.postgres_client import pg_client

_CONFIRM = "RECORD_ONE_DIRECT_BROKER_RECONCILIATION"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


async def execute(args: argparse.Namespace) -> dict[str, object]:
    request = DirectBrokerReconciliationRequest.model_validate_json(args.request.read_bytes())
    source_snapshot = json.loads(args.source_snapshot.read_text(encoding="utf-8"))
    await pg_client.initialize()
    try:
        repository = DirectBrokerReconciliationRepository(PostgresDirectBrokerReconciliationStore(pg_client))
        receipt, already_recorded = await repository.record(request, source_snapshot=source_snapshot)
        return {
            **receipt.model_dump(mode="json"),
            "disposition": "ALREADY_RECORDED" if already_recorded else "CREATED",
        }
    finally:
        await pg_client.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.confirm != _CONFIRM:
        parser.error(f"--confirm must equal {_CONFIRM}")
    if args.out.exists():
        parser.error("--out must not already exist")
    receipt = asyncio.run(execute(args))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
