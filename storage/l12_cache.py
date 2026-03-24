import contextlib
import json
import time
from typing import Any

from loguru import logger

from core.metrics import VERDICT_PATH_EVENT_TOTAL
from core.redis_keys import l12_verdict_meta
from infrastructure.redis_client import get_client
from journal.forensic_replay import append_replay_artifact
from storage.redis_client import redis_client

KEY_PREFIX = "L12:VERDICT:"
VERDICT_READY_CHANNEL = "events:l12_verdict_ready"
VERDICT_STREAM = "stream:l12_verdict"

# Durable Redis Stream for verdict events — survives subscriber disconnects.
VERDICT_STREAM = "stream:l12_verdict"
VERDICT_STREAM_MAXLEN = 1000

# TTL for verdict cache: 1 hour. Staleness detection uses _cached_at field
# comparison (see is_verdict_stale()), not TTL expiry. The TTL is a safety net
# for abandoned data only — the pipeline runs every ~60s under normal conditions.
VERDICT_TTL_SEC = 3600
# Maximum entries retained in the verdict stream (ring-buffer behaviour)
VERDICT_STREAM_MAXLEN = 1000


def set_verdict(pair: str, data: dict[str, Any]) -> None:
    # Inject server timestamp for staleness detection
    data_with_ts = {**data, "_cached_at": time.time()}
    redis_client.set(KEY_PREFIX + pair, json.dumps(data_with_ts), ex=VERDICT_TTL_SEC)
    logger.info("[VerdictPath] verdict persisted | pair={} key={} ttl={}s", pair, KEY_PREFIX + pair, VERDICT_TTL_SEC)
    VERDICT_PATH_EVENT_TOTAL.labels(event="verdict_persisted", symbol=pair, status="ok").inc()
    # Write slim metadata key for rapid health inspection (L12:VERDICT_META:<pair>)
    try:
        meta = {
            "pair": pair,
            "verdict": data_with_ts.get("verdict"),
            "confidence": data_with_ts.get("confidence"),
            "direction": data_with_ts.get("direction"),
            "cached_at": data_with_ts.get("_cached_at"),
            "timestamp": data_with_ts.get("timestamp"),
        }
        redis_client.set(l12_verdict_meta(pair), json.dumps(meta), ex=VERDICT_TTL_SEC)
    except Exception as exc:
        logger.debug("[VerdictPath] Failed to write verdict meta for {}: {}", pair, exc)
    event_payload = {
        "event": "VERDICT_READY",
        "pair": pair,
        "ts": time.time(),
    }
    # Durable event via Redis Stream (consumer-group safe, survives disconnect)
    with contextlib.suppress(Exception):
        redis_client.xadd(
            VERDICT_STREAM,
            {"pair": pair, "ts": str(time.time()), "data": json.dumps(data_with_ts)},
            maxlen=VERDICT_STREAM_MAXLEN,
            approximate=True,
        )
        logger.info("[VerdictPath] verdict stream published | pair={} stream={}", pair, VERDICT_STREAM)
        VERDICT_PATH_EVENT_TOTAL.labels(event="verdict_stream_published", symbol=pair, status="ok").inc()
    # Best-effort pub/sub for backward compat (ephemeral, may be lost)
    try:
        redis_client.publish(VERDICT_READY_CHANNEL, json.dumps(event_payload))
    except Exception:
        logger.warning("[L12Cache] Failed to publish VERDICT_READY for %s", pair, exc_info=True)
    with contextlib.suppress(Exception):
        append_replay_artifact(
            "verdict_provenance",
            correlation_id=str(data_with_ts.get("signal_id") or pair),
            payload={
                "pair": pair,
                "verdict": data_with_ts.get("verdict"),
                "confidence": data_with_ts.get("confidence"),
                "timestamp": data_with_ts.get("timestamp"),
                "cached_at": data_with_ts.get("_cached_at"),
                "scores": data_with_ts.get("scores"),
                "gates": data_with_ts.get("gates"),
            },
        )


async def set_verdict_async(pair: str, data: dict[str, Any]) -> None:
    data_with_ts = {**data, "_cached_at": time.time()}
    client = await get_client()
    await client.set(KEY_PREFIX + pair, json.dumps(data_with_ts), ex=VERDICT_TTL_SEC)
    logger.info("[VerdictPath] verdict persisted | pair={} key={} ttl={}s", pair, KEY_PREFIX + pair, VERDICT_TTL_SEC)
    VERDICT_PATH_EVENT_TOTAL.labels(event="verdict_persisted", symbol=pair, status="ok").inc()
    # Write slim metadata key for rapid health inspection (L12:VERDICT_META:<pair>)
    try:
        meta = {
            "pair": pair,
            "verdict": data_with_ts.get("verdict"),
            "confidence": data_with_ts.get("confidence"),
            "direction": data_with_ts.get("direction"),
            "cached_at": data_with_ts.get("_cached_at"),
            "timestamp": data_with_ts.get("timestamp"),
        }
        await client.set(l12_verdict_meta(pair), json.dumps(meta), ex=VERDICT_TTL_SEC)
    except Exception as exc:
        logger.debug("[VerdictPath] Failed to write async verdict meta for {}: {}", pair, exc)
    event_payload = {
        "event": "VERDICT_READY",
        "pair": pair,
        "ts": time.time(),
    }
    # Durable event via Redis Stream
    with contextlib.suppress(Exception):
        await client.xadd(
            VERDICT_STREAM,
            {"pair": pair, "ts": str(time.time()), "data": json.dumps(data_with_ts)},
            maxlen=VERDICT_STREAM_MAXLEN,
            approximate=True,
        )
        logger.info("[VerdictPath] verdict stream published | pair={} stream={}", pair, VERDICT_STREAM)
        VERDICT_PATH_EVENT_TOTAL.labels(event="verdict_stream_published", symbol=pair, status="ok").inc()
    # Best-effort pub/sub for backward compat
    try:
        await client.publish(VERDICT_READY_CHANNEL, json.dumps(event_payload))
    except Exception:
        logger.warning("[L12Cache] Failed to publish async VERDICT_READY for %s", pair, exc_info=True)
    with contextlib.suppress(Exception):
        append_replay_artifact(
            "verdict_provenance",
            correlation_id=str(data_with_ts.get("signal_id") or pair),
            payload={
                "pair": pair,
                "verdict": data_with_ts.get("verdict"),
                "confidence": data_with_ts.get("confidence"),
                "timestamp": data_with_ts.get("timestamp"),
                "cached_at": data_with_ts.get("_cached_at"),
                "scores": data_with_ts.get("scores"),
                "gates": data_with_ts.get("gates"),
            },
        )


def get_verdict(pair: str) -> dict[str, Any] | None:
    raw = redis_client.get(KEY_PREFIX + pair)
    return json.loads(raw) if raw else None


async def get_verdict_async(pair: str) -> dict[str, Any] | None:
    client = await get_client()
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
    client = await get_client()
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
