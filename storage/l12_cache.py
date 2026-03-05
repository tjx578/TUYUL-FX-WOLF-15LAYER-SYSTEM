import contextlib
import json
import time
from typing import Any, cast

import redis.asyncio as aioredis

from infrastructure.redis_client import get_client
from storage.redis_client import redis_client

KEY_PREFIX = "L12:VERDICT:"
VERDICT_READY_CHANNEL = "events:l12_verdict_ready"

# TTL for verdict cache: 10 minutes. Prevents stale data lingering forever
# if the pipeline crashes. The pipeline runs every ~60s under normal conditions.
VERDICT_TTL_SEC = 600


def set_verdict(pair: str, data: dict[str, Any]) -> None:
    # Inject server timestamp for staleness detection
    data_with_ts = {**data, "_cached_at": time.time()}
    redis_client.set(KEY_PREFIX + pair, json.dumps(data_with_ts), ex=VERDICT_TTL_SEC)
    event_payload = {
        "event": "VERDICT_READY",
        "pair": pair,
        "ts": time.time(),
    }
    with contextlib.suppress(Exception):
        redis_client.publish(VERDICT_READY_CHANNEL, json.dumps(event_payload))


async def set_verdict_async(pair: str, data: dict[str, Any]) -> None:
    data_with_ts = {**data, "_cached_at": time.time()}
    client = cast("aioredis.Redis[bytes]", await get_client())
    await client.set(KEY_PREFIX + pair, json.dumps(data_with_ts), ex=VERDICT_TTL_SEC)
    event_payload = {
        "event": "VERDICT_READY",
        "pair": pair,
        "ts": time.time(),
    }
    with contextlib.suppress(Exception):
        await client.publish(VERDICT_READY_CHANNEL, json.dumps(event_payload))


def get_verdict(pair: str) -> dict[str, Any] | None:
    raw = redis_client.get(KEY_PREFIX + pair)
    return json.loads(raw) if raw else None


async def get_verdict_async(pair: str) -> dict[str, Any] | None:
    client = cast("aioredis.Redis[bytes]", await get_client())
    raw = await client.get(KEY_PREFIX + pair)
    return json.loads(raw) if raw else None


def is_verdict_stale(verdict: dict[str, Any] | None, max_age_sec: float = 300.0) -> bool:
    """Check if a verdict is stale (older than max_age_sec).

    This is a read-only utility — it does NOT make trade decisions.
    """
    if verdict is None:
        return True
    cached_at = verdict.get("_cached_at")
    if cached_at is None:
        # Legacy entry without timestamp — consider stale
        return True
    return (time.time() - float(cached_at)) > max_age_sec


def get_all_verdicts() -> list[dict[str, Any]]:
    all_verdicts = redis_client.get(KEY_PREFIX + "ALL")
    return json.loads(all_verdicts) if all_verdicts else []


async def get_all_verdicts_async() -> list[dict[str, Any]]:
    client = cast("aioredis.Redis[bytes]", await get_client())
    all_verdicts = await client.get(KEY_PREFIX + "ALL")
    return json.loads(all_verdicts) if all_verdicts else []


def filter_verdicts(
    all_verdicts: list[dict[str, Any]],
    filter_mode: str = "ALL",
    selected_pair: str = "ALL",
) -> list[dict[str, Any]]:
    """Filter verdicts by mode and pair, returning only non-stale entries."""
    filtered: list[dict[str, Any]] = []
    for v in all_verdicts:
        verdict_str = str(v.get("verdict", ""))
        match_mode = (
            filter_mode == "ALL"
            or (filter_mode == "EXECUTE" and verdict_str.startswith("EXECUTE"))
            or (filter_mode == "HOLD" and verdict_str == "HOLD")
        )
        match_pair = selected_pair == "ALL" or v.get("symbol") == selected_pair
        if match_mode and match_pair:
            filtered.append(v)

    return [v for v in filtered if not is_verdict_stale(v)]
