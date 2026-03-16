"""Regression tests for Redis key type sanitizer in main orchestrator."""

from __future__ import annotations

import pytest

from main import _sanitize_redis_keys


class _FakeRedis:
    def __init__(self, keys_by_pattern: dict[str, list[str]], key_types: dict[str, bytes | str]) -> None:
        self._keys_by_pattern = keys_by_pattern
        self._key_types = key_types
        self.deleted: list[str] = []

    async def keys(self, pattern: str) -> list[str]:
        return self._keys_by_pattern.get(pattern, [])

    async def type(self, key: str) -> bytes | str:
        return self._key_types.get(key, "none")

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


@pytest.mark.asyncio
async def test_sanitize_keeps_valid_list_keys_when_redis_type_is_bytes() -> None:
    redis = _FakeRedis(
        keys_by_pattern={"wolf15:candle_history:*": ["wolf15:candle_history:EURUSD:H1"]},
        key_types={"wolf15:candle_history:EURUSD:H1": b"list"},
    )

    await _sanitize_redis_keys(redis)  # type: ignore[arg-type]

    assert redis.deleted == []


@pytest.mark.asyncio
async def test_sanitize_deletes_conflicting_key_types_with_bytes_response() -> None:
    redis = _FakeRedis(
        keys_by_pattern={"wolf15:candle_history:*": ["wolf15:candle_history:EURUSD:H1"]},
        key_types={"wolf15:candle_history:EURUSD:H1": b"hash"},
    )

    await _sanitize_redis_keys(redis)  # type: ignore[arg-type]

    assert redis.deleted == ["wolf15:candle_history:EURUSD:H1"]
