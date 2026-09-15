"""Produce backend identity, collect an attestation, or import authenticated evidence.

No operation builds, enqueues, arms, or submits a broker command.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID


async def execute(args: argparse.Namespace) -> dict[str, object]:
    if args.operation == "collect":
        from ops.mt5_mcp.reconcile import run_reconciliation

        dsn = os.getenv("AUDIT_DATABASE_URL", "")
        if not dsn:
            raise ValueError("AUDIT_DATABASE_URL_NOT_PRESENT")
        report = await run_reconciliation(
            dsn=dsn, repo_root=Path(__file__).resolve().parents[1], config_path=args.config, attest=True
        )
        return report["reconciliation_attestation"]
    from execution.broker_reconciliation_repository import produce_backend_identity, store_evidence
    from storage.postgres_client import pg_client

    await pg_client.initialize()
    try:
        async with pg_client.transaction() as connection:
            if args.operation == "identity":
                return await produce_backend_identity(connection, args.executor_id)
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            receipt_digest = await store_evidence(connection, evidence)
            return {"evidence_id": evidence["evidence_id"], "sha256": receipt_digest, "status": "STORED"}
    finally:
        await pg_client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    identity = subparsers.add_parser("identity")
    identity.add_argument("--executor-id", type=UUID, required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--config", type=Path, required=True)
    ingest = subparsers.add_parser("import")
    ingest.add_argument("--evidence", type=Path, required=True)
    for command in (identity, collect, ingest):
        command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists")
    try:
        result = asyncio.run(execute(args))
        with args.out.open("x", encoding="utf-8") as output:
            json.dump(result, output, sort_keys=True, indent=2, default=str)
            output.write("\n")
    except Exception as exc:
        # Database exceptions can contain DSNs or query arguments.
        print(f"D0 reconciliation operation failed: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
