from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedisKeySnapshot:
    key: str
    exists: bool
    key_type: str
    pttl_milliseconds: int
    dump_payload: bytes | None
    cardinality: int
    captured_at_milliseconds: int


def _now_milliseconds() -> int:
    return time.monotonic_ns() // 1_000_000


def _cardinality(client: Any, key: str, key_type: str) -> int:
    readers = {
        "string": lambda: 1,
        "hash": lambda: int(client.hlen(key)),
        "set": lambda: int(client.scard(key)),
        "zset": lambda: int(client.zcard(key)),
        "list": lambda: int(client.llen(key)),
        "stream": lambda: int(client.xlen(key)),
    }
    try:
        reader = readers[key_type]
    except KeyError as exc:
        raise AssertionError(f"unsupported Redis fixture type for {key}: {key_type}") from exc
    return reader()


def capture_redis_key(
    client: Any,
    key: str,
    *,
    now_milliseconds: int | None = None,
) -> RedisKeySnapshot:
    captured_at = _now_milliseconds() if now_milliseconds is None else now_milliseconds
    key_type = str(client.type(key))
    if key_type == "none":
        return RedisKeySnapshot(key, False, "none", -2, None, 0, captured_at)
    payload = client.dump(key)
    if not isinstance(payload, bytes):
        raise AssertionError(f"Redis DUMP did not return bytes for {key}")
    return RedisKeySnapshot(
        key=key,
        exists=True,
        key_type=key_type,
        pttl_milliseconds=int(client.pttl(key)),
        dump_payload=payload,
        cardinality=_cardinality(client, key, key_type),
        captured_at_milliseconds=captured_at,
    )


def expected_remaining_pttl(
    snapshot: RedisKeySnapshot,
    *,
    now_milliseconds: int | None = None,
) -> int:
    if snapshot.pttl_milliseconds < 0:
        return snapshot.pttl_milliseconds
    current = _now_milliseconds() if now_milliseconds is None else now_milliseconds
    elapsed = max(0, current - snapshot.captured_at_milliseconds)
    return max(1, snapshot.pttl_milliseconds - elapsed)


def restore_redis_key(
    client: Any,
    snapshot: RedisKeySnapshot,
    *,
    now_milliseconds: int | None = None,
) -> None:
    if not snapshot.exists:
        client.delete(snapshot.key)
        return
    if snapshot.dump_payload is None:
        raise AssertionError(f"existing Redis snapshot has no DUMP payload: {snapshot.key}")
    remaining = expected_remaining_pttl(snapshot, now_milliseconds=now_milliseconds)
    restore_ttl = 0 if remaining == -1 else remaining
    client.restore(snapshot.key, restore_ttl, snapshot.dump_payload, replace=True)


def assert_redis_key_matches(
    client: Any,
    snapshot: RedisKeySnapshot,
    *,
    now_milliseconds: int | None = None,
    ttl_tolerance_milliseconds: int = 250,
) -> None:
    actual = capture_redis_key(client, snapshot.key, now_milliseconds=now_milliseconds)
    if actual.exists != snapshot.exists:
        raise AssertionError(f"Redis existence drift for {snapshot.key}")
    if not snapshot.exists:
        return
    if actual.key_type != snapshot.key_type:
        raise AssertionError(f"Redis type drift for {snapshot.key}")
    if actual.dump_payload != snapshot.dump_payload:
        raise AssertionError(f"Redis value drift for {snapshot.key}")
    if actual.cardinality != snapshot.cardinality:
        raise AssertionError(f"Redis cardinality drift for {snapshot.key}")

    expected_pttl = expected_remaining_pttl(snapshot, now_milliseconds=now_milliseconds)
    if expected_pttl == -1:
        if actual.pttl_milliseconds != -1:
            raise AssertionError(f"Redis persistence policy drift for {snapshot.key}")
    elif actual.pttl_milliseconds < 0 or abs(actual.pttl_milliseconds - expected_pttl) > ttl_tolerance_milliseconds:
        raise AssertionError(f"Redis TTL drift for {snapshot.key}")


def assert_only_declared_keys_changed(
    before: Mapping[str, str],
    after: Mapping[str, str],
    declared_keys: set[str],
) -> None:
    changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
    unowned = sorted(changed - declared_keys)
    if unowned:
        raise AssertionError(f"Redis fixture mutated unowned keys: {unowned}")
