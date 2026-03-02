"""Tests for CANDLE_HISTORY_KEY_PREFIXES env-override in RedisConsumer.

Zone: analysis/context — no execution side-effects.

These tests specifically exercise the runtime env-override path so DB/namespace
mismatches can be fixed without code changes (env var only).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, TypedDict, cast
from unittest.mock import MagicMock

import orjson
import pytest

from context.live_context_bus import LiveContextBus
from context.redis_consumer import RedisConsumer
from context.redis_consumer import (
    get_candle_prefixes as _get_candle_prefixes_raw,  # type: ignore
)

_get_candle_prefixes_raw_typed: Callable[[], list[str]] = cast(
    Callable[[], list[str]], _get_candle_prefixes_raw
)
get_candle_prefixes = _get_candle_prefixes_raw_typed

pytestmark = pytest.mark.anyio

_ENV_KEY = "CANDLE_HISTORY_KEY_PREFIXES"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle(symbol: str, timeframe: str, close: float) -> bytes:
    return orjson.dumps({"symbol": symbol, "timeframe": timeframe, "close": close})


def _make_redis(list_data: dict[str, list[bytes]] | None = None) -> MagicMock:
    redis = MagicMock()
    _ld = list_data or {}

    async def lrange(key: str, start: int, end: int) -> list[bytes]:
        return _ld.get(key, [])

    async def hgetall(key: str) -> dict[str | bytes, str | bytes]:
        return {}

    redis.lrange = lrange
    redis.hgetall = hgetall
    redis.pubsub = MagicMock(return_value=MagicMock())
    return redis


@pytest.fixture(autouse=True)
def clean_env():
    """Ensure CANDLE_HISTORY_KEY_PREFIXES is unset before and after each test."""
    os.environ.pop(_ENV_KEY, None)
    yield
    os.environ.pop(_ENV_KEY, None)


# ---------------------------------------------------------------------------
# Unit: _get_candle_prefixes()
# ---------------------------------------------------------------------------

def test_default_prefixes_when_env_not_set() -> None:
    """get_candle_prefixes returns module defaults when env var absent."""
    from context.redis_consumer import CANDLE_HISTORY_LIST_PREFIXES

    result: list[str] = get_candle_prefixes()
    assert result == list(CANDLE_HISTORY_LIST_PREFIXES)


def test_env_override_single_prefix() -> None:
    """Single custom prefix via env var."""
    os.environ[_ENV_KEY] = "myns:candle_history"
    assert get_candle_prefixes() == ["myns:candle_history"]


def test_env_override_multiple_prefixes() -> None:
    """Comma-separated prefixes are split and stripped."""
    os.environ[_ENV_KEY] = "wolf15:candle_history , candle_history , legacy:candles"
    assert get_candle_prefixes() == [
        "wolf15:candle_history",
        "candle_history",
        "legacy:candles",
    ]


def test_env_empty_string_falls_back_to_defaults() -> None:
    """Empty string env var should use defaults, not produce empty list."""
    from context.redis_consumer import CANDLE_HISTORY_LIST_PREFIXES

    os.environ[_ENV_KEY] = "   "
    assert get_candle_prefixes() == list(CANDLE_HISTORY_LIST_PREFIXES)


def test_env_trailing_commas_are_ignored() -> None:
    """Trailing commas after split must not introduce empty strings."""
    os.environ[_ENV_KEY] = "wolf15:candle_history,"
    result: list[str] = get_candle_prefixes()
    assert "" not in result
    assert result == ["wolf15:candle_history"]


# ---------------------------------------------------------------------------
# DB index mismatch simulation
# ---------------------------------------------------------------------------

async def test_db_mismatch_scenario_no_data() -> None:
    """Simulates DB mismatch: writer uses one prefix, reader uses another → 0 bars.

    Uses unique symbol NZDUSD to avoid cross-test bus state contamination.
    """
    # No env override — reader uses default wolf15:candle_history
    # Writer stores under ohlcv: (different db/prefix)
    candle = _make_candle("NZDUSD", "H1", 0.6100)
    redis = _make_redis({"ohlcv:NZDUSD:H1": [candle]})  # wrong namespace
    bus = LiveContextBus()

    consumer = RedisConsumer(["NZDUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("NZDUSD", "H1")
    assert history is None or len(history) == 0  # confirms mismatch yields 0 bars


async def test_db_mismatch_fixed_via_env() -> None:
    """After setting env to writer's prefix, data is found immediately."""
    os.environ[_ENV_KEY] = "ohlcv"  # match writer's namespace
    candle = _make_candle("NZDUSD", "H1", 0.6100)
    redis = _make_redis({"ohlcv:NZDUSD:H1": [candle]})
    bus = LiveContextBus()

    consumer = RedisConsumer(["NZDUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("NZDUSD", "H1")
    assert history is not None and len(history) == 1
    assert history[0]["close"] == pytest.approx(0.6100)  # type: ignore[reportUnknownMemberType]


# --- additional unit tests ---

def test_env_ignores_empty_tokens_between_commas() -> None:
    """Empty tokens are removed while preserving non-empty order."""
    os.environ[_ENV_KEY] = "primary:candles, ,secondary:candles,,legacy:candles"
    result: list[str] = get_candle_prefixes()
    assert result == ["primary:candles", "secondary:candles", "legacy:candles"]


def test_env_only_commas_falls_back_to_defaults() -> None:
    """Comma-only env should behave like empty input and use defaults."""
    from context.redis_consumer import CANDLE_HISTORY_LIST_PREFIXES

    os.environ[_ENV_KEY] = ", , ,,"
    result: list[str] = get_candle_prefixes()
    assert result == list(CANDLE_HISTORY_LIST_PREFIXES)


# --- additional integration tests ---

async def test_env_prefixes_are_stripped_before_lookup() -> None:
    """Leading/trailing spaces in env prefixes are stripped for Redis key lookup."""
    os.environ[_ENV_KEY] = "  custom:bars  "
    candle = _make_candle("USDJPY", "M5", 154.321)
    redis = _make_redis({"custom:bars:USDJPY:M5": [candle]})
    bus = LiveContextBus()

    consumer = RedisConsumer(["USDJPY"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("USDJPY", "M5")
    assert history is not None and len(history) == 1
    assert history[0]["close"] == pytest.approx(154.321)  # type: ignore[reportUnknownMemberType]


async def test_env_override_can_load_multiple_symbols_independently() -> None:
    """Custom env prefix should load data per symbol without cross-symbol leakage."""
    os.environ[_ENV_KEY] = "custom:bars"
    eurusd = _make_candle("EURUSD", "H1", 1.1010)
    usdcad = _make_candle("USDCAD", "H1", 1.3570)

    redis = _make_redis(
        {
            "custom:bars:EURUSD:H1": [eurusd],
            "custom:bars:USDCAD:H1": [usdcad],
        }
    )
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD", "USDCAD"], redis, bus)
    await consumer.load_candle_history()

    h_eurusd: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    h_usdcad: list[dict[str, Any]] | None = bus.get_candle_history("USDCAD", "H1")

    assert h_eurusd is not None and len(h_eurusd) == 1
    assert h_usdcad is not None and len(h_usdcad) == 1
    assert h_eurusd[0]["close"] == pytest.approx(1.1010)  # type: ignore[reportUnknownMemberType]
    assert h_usdcad[0]["close"] == pytest.approx(1.3570)  # type: ignore[reportUnknownMemberType]


class SignalResult(TypedDict):
    symbol: str
    verdict: str
    confidence: float
