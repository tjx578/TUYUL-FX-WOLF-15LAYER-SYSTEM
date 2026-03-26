"""
Redis Context Reader — Dashboard-Safe Context Provider.

Drop-in replacement for LiveContextBus in api/ layer.
Reads ALL data from Redis (written by engine/ingest services)
instead of in-process memory (which is empty in dashboard container).

Why this exists:
  LiveContextBus is a per-process singleton. Engine service writes data
  to its instance. Dashboard service has a SEPARATE instance that is
  always empty — get_candles() returns [], get_latest_tick() returns None.

  This class provides the SAME interface but reads from Redis, which
  both services share. Dashboard gets real data without importing
  engine-only modules (state.data_freshness, config.pip_values).

Interface compatibility:
  .snapshot()                    → full context snapshot (data + inference)
  .get_candles(symbol, tf)       → candle history from Redis LIST
  .get_candle(symbol, tf)        → latest candle
  .get_latest_tick(symbol)       → latest tick from Redis HASH
  .inference_snapshot()          → inference state (regime, session, etc.)
  .get_feed_status(symbol)       → feed freshness from Redis timestamps
  .check_warmup(symbol, min_bars)→ warmup readiness check
  .warmup_state                  → warmup summary

Zone: api/ — presentation layer. Read-only, no execution authority.
"""

from __future__ import annotations

import json
import time
from typing import Any, cast

from storage.redis_client import redis_client

# Key prefixes (must match what engine/ingest write)
_CANDLE_HISTORY = "wolf15:candle_history"
_LATEST_TICK = "wolf15:latest_tick"  # or ctx:tick:latest
_INFERENCE = "wolf15:inference"
_REGIME = "wolf15:regime_state"
_SESSION = "wolf15:session_state"
_NEWS_PRESSURE = "wolf15:news_pressure"
_FEED_TS = "wolf15:feed_ts"

# Warmup requirements (mirrors wolf_constitutional_pipeline.py)
_WARMUP_MIN_BARS = {"H1": 20, "H4": 10, "D1": 5, "W1": 5, "MN": 2}

# Timeframes to check
_ALL_TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1", "W1", "MN")


def _redis_lrange(key: str, start: int, end: int) -> list[str]:
    """Safe Redis LRANGE returning decoded strings."""
    try:
        raw = cast(list[Any], redis_client.client.lrange(key, start, end))
        if not raw:
            return []
        return [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in raw]
    except Exception:
        return []


def _redis_hgetall(key: str) -> dict[str, str]:
    """Safe Redis HGETALL returning decoded dict."""
    try:
        raw = cast(dict[Any, Any], redis_client.client.hgetall(key))
        if not raw:
            return {}
        return {
            (k.decode() if isinstance(k, bytes) else str(k)): (v.decode() if isinstance(v, bytes) else str(v))
            for k, v in raw.items()
        }
    except Exception:
        return {}


def _redis_get(key: str) -> str | None:
    """Safe Redis GET returning decoded string."""
    try:
        raw = redis_client.client.get(key)
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    except Exception:
        return None


def _parse_json_list(items: list[str]) -> list[dict[str, Any]]:
    """Parse list of JSON strings into list of dicts."""
    result = []
    for item in items:
        try:
            parsed = json.loads(item)
            if isinstance(parsed, dict):
                result.append(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


class RedisContextReader:
    """Redis-backed context reader for dashboard/api layer.

    Provides the same interface as LiveContextBus but reads from
    Redis. Safe to use in dashboard container where LiveContextBus
    singleton is empty.

    Thread-safe: all reads are stateless Redis queries, no internal
    mutable state, no locks needed.

    Usage (in l12_routes.py):
        # BEFORE:
        from context.live_context_bus import LiveContextBus
        context_bus = cast(_SnapshotProvider, LiveContextBus())

        # AFTER:
        from api.redis_context_reader import RedisContextReader
        context_bus = RedisContextReader()
    """

    def snapshot(self) -> dict[str, Any]:
        """Return full context snapshot from Redis.

        Mirrors LiveContextBus.snapshot() output format:
        {
            "candles": {key: [candle_dict, ...]},
            "ticks": {symbol: tick_dict},
            "inference": { regime, volatility, session, ... },
            "meta": { inference_ts, volatility_regime },
        }
        """
        candles = self._read_all_candles()
        ticks = self._read_all_ticks()
        inference = self.inference_snapshot()

        return {
            "candles": candles,
            "ticks": ticks,
            "conditioned_returns": {},
            "conditioning_meta": {},
            "macro": inference.get("regime_state", {}),
            "news": {},
            "inference": inference,
            "meta": {
                "inference_ts": inference.get("inference_ts", 0),
                "volatility_regime": inference.get("volatility_regime", "NORMAL"),
            },
        }

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return candle history from Redis LIST.

        Mirrors LiveContextBus.get_candles().
        """
        key = f"{_CANDLE_HISTORY}:{symbol}:{timeframe}"
        limit = count if count else 250
        items = _redis_lrange(key, -limit, -1)
        return _parse_json_list(items)

    def get_candle(
        self,
        symbol: str,
        timeframe: str,
    ) -> dict[str, Any] | None:
        """Return latest candle for symbol/timeframe.

        Mirrors LiveContextBus.get_candle().
        """
        key = f"{_CANDLE_HISTORY}:{symbol}:{timeframe}"
        items = _redis_lrange(key, -1, -1)
        parsed = _parse_json_list(items)
        return parsed[0] if parsed else None

    def get_candle_history(
        self,
        symbol: str,
        timeframe: str,
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Alias for get_candles (backward compat).

        Mirrors LiveContextBus.get_candle_history().
        """
        return self.get_candles(symbol, timeframe, count)

    def get_latest_tick(
        self,
        symbol: str,
    ) -> dict[str, Any] | None:
        """Return latest tick from Redis HASH.

        Mirrors LiveContextBus.get_latest_tick().
        """
        key = f"{_LATEST_TICK}:{symbol}"
        data = _redis_hgetall(key)
        if not data:
            return None

        # Convert string values to appropriate types
        result: dict[str, Any] = {"symbol": symbol}
        for k, v in data.items():
            try:
                result[k] = float(v)
            except (ValueError, TypeError):
                result[k] = v
        return result

    def inference_snapshot(self) -> dict[str, Any]:
        """Return inference state from Redis.

        Mirrors LiveContextBus.inference_snapshot().
        """
        regime = self._read_hash_or_json(_REGIME)
        session = self._read_hash_or_json(_SESSION)
        news_pressure = self._read_hash_or_json(_NEWS_PRESSURE)

        volatility_regime = "NORMAL"
        rs = regime.get("regime_state")
        if rs is not None:
            try:
                rs_int = int(float(rs))
                if rs_int == 0:
                    volatility_regime = "LOW"
                elif rs_int == 2:
                    volatility_regime = "HIGH"
            except (ValueError, TypeError):
                pass
        vr_override = regime.get("vix_regime")
        if vr_override and vr_override != "NORMAL":
            volatility_regime = str(vr_override)

        return {
            "regime_state": regime,
            "volatility_regime": volatility_regime,
            "session_state": session,
            "liquidity_map": {},
            "news_pressure_vector": news_pressure,
            "signal_stack": [],
            "inference_ts": float(regime.get("timestamp", 0) or session.get("timestamp", 0) or 0),
        }

    def get_macro_state(self) -> dict[str, Any]:
        """Return macro regime state from Redis."""
        return self._read_hash_or_json(_REGIME)

    def get_session_state(self) -> dict[str, Any]:
        """Return session state from Redis."""
        return self._read_hash_or_json(_SESSION)

    def get_volatility_regime(self) -> str:
        """Return current volatility regime label."""
        return self.inference_snapshot().get("volatility_regime", "NORMAL")

    def get_news_pressure(self) -> dict[str, Any]:
        """Return news pressure vector from Redis."""
        return self._read_hash_or_json(_NEWS_PRESSURE)

    def get_signal_stack(self) -> list[dict[str, Any]]:
        """Return signal stack (empty — signals are ephemeral)."""
        return []

    def get_feed_age(self, symbol: str) -> float | None:
        """Return seconds since last feed update."""
        ts = self._get_feed_timestamp(symbol)
        if ts is None:
            return None
        return time.time() - ts

    def get_feed_status(self, symbol: str) -> str:
        """Return feed freshness class.

        Simplified version without state.data_freshness dependency.
        """
        ts = self._get_feed_timestamp(symbol)
        if ts is None:
            return "NO_PRODUCER"
        age = time.time() - ts
        if age < 30:
            return "LIVE"
        elif age < 120:
            return "DEGRADED_BUT_REFRESHING"
        else:
            return "STALE_PRESERVED"

    def is_feed_stale(
        self,
        symbol: str,
        threshold_sec: float | None = None,
    ) -> bool:
        """Return True if feed is stale."""
        if threshold_sec is None:
            threshold_sec = 120.0
        age = self.get_feed_age(symbol)
        if age is None:
            return True
        return age > threshold_sec

    def get_warmup_bar_count(
        self,
        symbol: str,
        timeframe: str,
    ) -> int:
        """Return bar count for symbol/timeframe from Redis."""
        key = f"{_CANDLE_HISTORY}:{symbol}:{timeframe}"
        try:
            return cast(int, redis_client.client.llen(key)) or 0
        except Exception:
            return 0

    def check_warmup(
        self,
        symbol: str,
        min_bars: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Check warmup readiness from Redis bar counts.

        Mirrors LiveContextBus.check_warmup().
        """
        if min_bars is None:
            min_bars = _WARMUP_MIN_BARS

        bars: dict[str, int] = {}
        required_map: dict[str, int] = {}
        missing: dict[str, int] = {}
        details: dict[str, dict[str, int]] = {}
        ready = True

        for tf, need in min_bars.items():
            have = self.get_warmup_bar_count(symbol, tf)
            bars[tf] = have
            required_map[tf] = need
            shortfall = max(0, need - have)
            details[tf] = {
                "have": have,
                "need": need,
                "missing": shortfall,
            }
            if shortfall > 0:
                ready = False
                missing[tf] = shortfall

        return {
            "ready": ready,
            "bars": bars,
            "required": required_map,
            "missing": missing,
            "details": details,
        }

    @property
    def warmup_state(self) -> dict[str, Any]:
        """Return warmup readiness summary.

        Mirrors LiveContextBus.warmup_state.
        """
        symbols: dict[str, dict[str, Any]] = {}

        # Scan Redis for known candle_history keys
        try:
            keys = cast(list[Any], redis_client.client.keys(f"{_CANDLE_HISTORY}:*"))
        except Exception:
            keys = []

        seen: set[str] = set()
        for k in keys:
            key_str = k.decode() if isinstance(k, bytes) else str(k)
            parts = key_str.replace(f"{_CANDLE_HISTORY}:", "").split(":", 1)
            if parts:
                seen.add(parts[0])

        for sym in seen:
            bar_counts: dict[str, int] = {}
            for tf in _ALL_TIMEFRAMES:
                count = self.get_warmup_bar_count(sym, tf)
                if count > 0:
                    bar_counts[tf] = count
            symbols[sym] = {
                "ready": any(c > 0 for c in bar_counts.values()),
                "bar_counts": bar_counts,
            }

        return {"symbols": symbols}

    def check_price_drift(
        self,
        symbol: str,
        max_drift_pips: float = 5.0,
    ) -> dict[str, Any]:
        """Check price drift (simplified, no pip_values dependency)."""
        h1_candles = self.get_candles(symbol, "H1", count=1)
        rest_close = float(h1_candles[-1].get("close", 0)) if h1_candles else None

        tick = self.get_latest_tick(symbol)
        ws_mid: float | None = None
        if tick:
            bid = tick.get("bid") or tick.get("price")
            ask = tick.get("ask") or tick.get("price")
            if bid is not None and ask is not None:
                ws_mid = (float(bid) + float(ask)) / 2.0
            elif bid is not None:
                ws_mid = float(bid)

        if rest_close is None or ws_mid is None:
            return {
                "drifted": False,
                "drift_pips": 0.0,
                "rest_close": rest_close,
                "ws_mid": ws_mid,
            }

        # Default multiplier (most forex pairs)
        multiplier = 10000.0
        sym_upper = symbol.upper()
        if "JPY" in sym_upper:
            multiplier = 100.0
        elif "XAU" in sym_upper:
            multiplier = 10.0

        drift_pips = abs(rest_close - ws_mid) * multiplier
        return {
            "drifted": drift_pips > max_drift_pips,
            "drift_pips": round(drift_pips, 1),
            "rest_close": rest_close,
            "ws_mid": ws_mid,
        }

    # ── Internal helpers ──────────────────────────────────────

    def _get_feed_timestamp(self, symbol: str) -> float | None:
        """Read feed timestamp from Redis."""
        key = f"{_FEED_TS}:{symbol}"
        val = _redis_get(key)
        if val is None:
            # Fallback: check tick timestamp
            tick = self.get_latest_tick(symbol)
            if tick:
                ts = tick.get("timestamp") or tick.get("ts")
                if ts is not None:
                    return float(ts)
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _read_hash_or_json(self, key: str) -> dict[str, Any]:
        """Read a Redis key as HASH or JSON string."""
        data = _redis_hgetall(key)
        if data:
            return data
        # Fallback: try as JSON string
        val = _redis_get(key)
        if val:
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    def _read_all_candles(self) -> dict[str, list[dict[str, Any]]]:
        """Read all candle history keys from Redis."""
        result: dict[str, list[dict[str, Any]]] = {}
        try:
            keys = cast(list[Any], redis_client.client.keys(f"{_CANDLE_HISTORY}:*"))
        except Exception:
            return result

        for k in keys:
            key_str = k.decode() if isinstance(k, bytes) else str(k)
            short_key = key_str.replace(f"{_CANDLE_HISTORY}:", "")
            items = _redis_lrange(key_str, -50, -1)
            if items:
                result[short_key] = _parse_json_list(items)

        return result

    def _read_all_ticks(self) -> dict[str, dict[str, Any]]:
        """Read all latest ticks from Redis."""
        result: dict[str, dict[str, Any]] = {}
        try:
            keys = cast(list[Any], redis_client.client.keys(f"{_LATEST_TICK}:*"))
        except Exception:
            return result

        for k in keys:
            key_str = k.decode() if isinstance(k, bytes) else str(k)
            sym = key_str.replace(f"{_LATEST_TICK}:", "")
            data = _redis_hgetall(key_str)
            if data:
                tick: dict[str, Any] = {"symbol": sym}
                for field, val in data.items():
                    try:
                        tick[field] = float(val)
                    except (ValueError, TypeError):
                        tick[field] = val
                result[sym] = tick

        return result
