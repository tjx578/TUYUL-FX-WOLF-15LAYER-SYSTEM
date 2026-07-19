"""Export canonical pressure replay input from PostgreSQL outbox rows."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from typing import Any

from storage.postgres_client import pg_client
from storage.pressure_outbox import PressureOutboxRepository


def _datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _export(args: argparse.Namespace) -> int:
    await pg_client.initialize()
    if not pg_client.is_available:
        raise RuntimeError("DATABASE_URL is required for pressure outbox replay")
    try:
        events = await PressureOutboxRepository(pg=pg_client).load_replay_events(
            lifecycle_id=args.lifecycle_id,
            since=_datetime(args.since),
            until=_datetime(args.until),
            limit=args.limit,
        )
        for event in events:
            record: dict[str, Any] = event.model_dump(mode="json")
            print(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
        return len(events)
    finally:
        await pg_client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifecycle-id")
    parser.add_argument("--since", help="Inclusive ISO-8601 signal-valid timestamp")
    parser.add_argument("--until", help="Inclusive ISO-8601 signal-valid timestamp")
    parser.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args()
    asyncio.run(_export(args))


if __name__ == "__main__":
    main()
