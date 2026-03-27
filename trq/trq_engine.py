"""TRQ-3D Quad PreMove Engine v6.0 — Zone A micro-wave analysis.

Zone: trq/ — reads from Redis, publishes TRQ signals. No pipeline modification.

Architecture
------------
Reads M1/M5/M15/H1 candle histories from Redis (wolf15:candle_history:{SYM}:{TF}),
computes TRQ-3D with Monte Carlo, Quad Coupling, CONF12, and WLWCI, then
publishes via TRQRedisBridge.

Critical fixes vs. earlier drafts
----------------------------------
1. Monte Carlo seed: Uses SHA256 hash of the polar array bytes — eliminates
   the collision risk of the old ``int(polar[-1] * 1e6) & 0xFFFFFFFF`` seed
   (two different negative values with same lower-32 bits produced identical
   Monte Carlo outputs).

2. Class name typo: ``_RedisCandleReader`` (was ``_RedisCandelReader``).

3. Deterministic volume split: Uses SHA256 hash of bar index and symbol bytes.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from typing import Any

import numpy as np
import orjson
from loguru import logger

from core.redis_keys import candle_history
from trq.trq_redis_bridge import TRQRedisBridge

# ── Poll interval ─────────────────────────────────────────────────────────────
_POLL_INTERVAL_SEC = 5.0

# ── History lengths needed per timeframe ─────────────────────────────────────
_REQUIRED_BARS: dict[str, int] = {
    "M1": 60,
    "M5": 30,
    "M15": 20,
    "H1": 20,
}


# ══════════════════════════════════════════════════════════════════════════════
#  Redis candle reader
# ══════════════════════════════════════════════════════════════════════════════


class _RedisCandleReader:
    """Async reader for candle history lists from Redis."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def read(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        """Return up to *count* most-recent candles from the history list."""
        key = candle_history(symbol, timeframe)
        try:
            raw_entries: list[Any] = await self._redis.lrange(key, -count, -1)
        except Exception as exc:
            logger.warning("[TRQEngine] Redis read failed {} {}: {}", symbol, timeframe, exc)
            return []

        candles: list[dict[str, Any]] = []
        for entry in raw_entries:
            try:
                data = orjson.loads(entry) if isinstance(entry, (bytes, str)) else entry
                candles.append(data)
            except Exception:
                pass
        return candles


# ══════════════════════════════════════════════════════════════════════════════
#  TRQ computation helpers
# ══════════════════════════════════════════════════════════════════════════════


def _close_array(candles: list[dict[str, Any]]) -> np.ndarray:
    """Extract close prices as a numpy float64 array."""
    closes = []
    for c in candles:
        with contextlib.suppress(KeyError, TypeError, ValueError):
            closes.append(float(c["close"]))
    return np.array(closes, dtype=np.float64)


def _polar_transform(closes: np.ndarray) -> np.ndarray:
    """Convert price deltas to polar (angle) representation."""
    if len(closes) < 2:
        return np.zeros(1, dtype=np.float64)
    deltas = np.diff(closes)
    # Normalize to [-pi, pi] range via arctan scaling
    std = float(np.std(deltas))
    scale = std if std > 0 else 1.0
    return np.arctan(deltas / scale)


def _sha256_seed(arr: np.ndarray) -> int:
    """Derive a deterministic 64-bit RNG seed from array bytes via SHA256.

    Uses SHA256 to eliminate collision risk for negative R3D values —
    two different negative values sharing the same lower 32 bits no longer
    produce identical Monte Carlo outputs.
    """
    seed_bytes = hashlib.sha256(arr.tobytes()).digest()[:8]
    return int.from_bytes(seed_bytes, "big")


def _deterministic_volume_split(symbol: str, bar_idx: int, n_buckets: int) -> int:
    """Return a deterministic bucket index via SHA256 of symbol + bar_idx."""
    if n_buckets <= 0:
        raise ValueError("n_buckets must be > 0")
    key = f"{symbol}:{bar_idx}".encode()
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:4], "big") % n_buckets


def _compute_r3d(
    closes_m1: np.ndarray,
    closes_m5: np.ndarray,
    closes_m15: np.ndarray,
    closes_h1: np.ndarray,
) -> float:
    """Compute R3D: composite energy across four timeframe polar arrays."""
    arrays = [closes_m1, closes_m5, closes_m15, closes_h1]
    weights = [0.15, 0.25, 0.30, 0.30]  # M1→H1 increasing weight

    energies: list[float] = []
    for arr in arrays:
        if len(arr) < 2:
            energies.append(0.0)
            continue
        polar = _polar_transform(arr)
        # Energy = mean absolute polar angle
        energies.append(float(np.mean(np.abs(polar))))

    r3d = sum(w * e for w, e in zip(weights, energies, strict=False))
    return round(r3d, 6)


def _monte_carlo_conf(polar: np.ndarray, n_sims: int = 500) -> float:
    """Run Monte Carlo simulation to compute CONF12 confidence [0, 1].

    Seed is derived from SHA256 hash of polar array bytes — deterministic
    and collision-free across all possible polar distributions.
    """
    if len(polar) < 3:
        return 0.5

    seed = _sha256_seed(polar)
    rng = np.random.default_rng(seed=seed)

    # Bootstrap: resample polar angles, measure directional consistency
    direction = float(np.sign(np.mean(polar)))
    if direction == 0.0:
        return 0.5

    consistent = 0
    for _ in range(n_sims):
        sample = rng.choice(polar, size=len(polar), replace=True)
        sim_dir = float(np.sign(np.mean(sample)))
        if sim_dir == direction:
            consistent += 1

    return round(consistent / n_sims, 4)


def _compute_wlwci(
    closes_m1: np.ndarray,
    closes_m5: np.ndarray,
    closes_m15: np.ndarray,
    closes_h1: np.ndarray,
) -> float:
    """Wolf-Level Weighted Confluence Index — range [-1, 1].

    Positive → bullish confluence, negative → bearish confluence.
    """
    arrays = [closes_m1, closes_m5, closes_m15, closes_h1]
    weights = [0.10, 0.20, 0.30, 0.40]

    signals: list[float] = []
    for arr in arrays:
        if len(arr) < 2:
            signals.append(0.0)
            continue
        polar = _polar_transform(arr)
        # Weighted mean angle sign = directional signal
        signals.append(float(np.tanh(np.mean(polar) * 10)))  # tanh compression

    wlwci = sum(w * s for w, s in zip(weights, signals, strict=False))
    return round(max(-1.0, min(1.0, wlwci)), 4)


def _quad_coupling_energy(
    closes_m1: np.ndarray,
    closes_m5: np.ndarray,
    closes_m15: np.ndarray,
    closes_h1: np.ndarray,
) -> float:
    """Quad coupling: 4-field resonance energy [0, ∞).

    Measures how aligned the four timeframe momentum fields are.
    Higher value = stronger multi-TF confluence.
    """
    arrays = [closes_m1, closes_m5, closes_m15, closes_h1]
    polars: list[np.ndarray] = []
    for arr in arrays:
        if len(arr) < 2:
            polars.append(np.zeros(1))
        else:
            polars.append(_polar_transform(arr))

    # Mean direction per TF
    means = [float(np.mean(p)) for p in polars]
    # Cross-TF correlation energy: variance of means → low variance = high coupling
    variance = float(np.var(np.array(means)))
    # Invert and normalize: 1/(1+variance) × baseline_energy
    baseline = float(np.mean([float(np.mean(np.abs(p))) for p in polars]))
    return round(baseline / (1.0 + variance), 6)


def _classify_verdict(r3d: float, conf12: float, wlwci: float) -> str:
    """Classify TRQ pre-move verdict from computed scores."""
    if conf12 < 0.55:
        return "NEUTRAL"
    if r3d < 0.01:
        return "NEUTRAL"
    if wlwci >= 0.30:
        return "BULLISH"
    if wlwci <= -0.30:
        return "BEARISH"
    return "NEUTRAL"


# ══════════════════════════════════════════════════════════════════════════════
#  TRQEngine
# ══════════════════════════════════════════════════════════════════════════════


class TRQEngine:
    """TRQ-3D Quad PreMove Engine v6.0.

    Polls Redis candle histories for M1/M5/M15/H1, computes TRQ-3D metrics,
    and publishes pre-move signals via TRQRedisBridge.

    Usage::

        engine = TRQEngine(redis, symbols=["EURUSD", "GBPUSD"])
        await engine.run()  # blocks; cancel to stop
    """

    def __init__(
        self,
        redis: Any,
        symbols: list[str],
        poll_interval: float = _POLL_INTERVAL_SEC,
    ) -> None:
        self._redis = redis
        self._symbols = symbols
        self._poll_interval = poll_interval
        self._reader = _RedisCandleReader(redis)
        self._bridge = TRQRedisBridge(redis)
        self._cycle_count: int = 0

    async def run(self) -> None:
        """Main loop: poll → compute → publish."""
        logger.info("[TRQEngine] Started for {} symbols", len(self._symbols))
        try:
            while True:
                start = time.monotonic()
                await self._run_cycle()
                elapsed = time.monotonic() - start
                sleep = max(0.0, self._poll_interval - elapsed)
                await asyncio.sleep(sleep)
        except asyncio.CancelledError:
            logger.info("[TRQEngine] Stopped after {} cycles", self._cycle_count)
            raise

    async def _run_cycle(self) -> None:
        """Process all symbols in one cycle."""
        self._cycle_count += 1
        for symbol in self._symbols:
            try:
                await self._process_symbol(symbol)
            except Exception as exc:
                logger.warning("[TRQEngine] Error processing {}: {}", symbol, exc)

    async def _process_symbol(self, symbol: str) -> None:
        """Compute and publish TRQ metrics for one symbol."""
        # Read candle histories
        candles_m1 = await self._reader.read(symbol, "M1", _REQUIRED_BARS["M1"])
        candles_m5 = await self._reader.read(symbol, "M5", _REQUIRED_BARS["M5"])
        candles_m15 = await self._reader.read(symbol, "M15", _REQUIRED_BARS["M15"])
        candles_h1 = await self._reader.read(symbol, "H1", _REQUIRED_BARS["H1"])

        # Require at least 2 bars on each TF for meaningful computation
        if any(len(c) < 2 for c in [candles_m1, candles_m5, candles_m15, candles_h1]):
            return

        closes_m1 = _close_array(candles_m1)
        closes_m5 = _close_array(candles_m5)
        closes_m15 = _close_array(candles_m15)
        closes_h1 = _close_array(candles_h1)

        r3d = _compute_r3d(closes_m1, closes_m5, closes_m15, closes_h1)

        # Monte Carlo CONF12: use H1 polar as the primary confidence signal
        polar_h1 = _polar_transform(closes_h1)
        conf12 = _monte_carlo_conf(polar_h1)

        wlwci = _compute_wlwci(closes_m1, closes_m5, closes_m15, closes_h1)
        quad_energy = _quad_coupling_energy(closes_m1, closes_m5, closes_m15, closes_h1)
        verdict = _classify_verdict(r3d, conf12, wlwci)

        await self._bridge.publish(
            symbol=symbol,
            verdict=verdict,
            r3d=r3d,
            conf12=conf12,
            wlwci=wlwci,
            quad_energy=quad_energy,
        )

    def health(self) -> dict[str, Any]:
        """Return engine health for monitoring."""
        return {
            "symbols": self._symbols,
            "cycle_count": self._cycle_count,
            "bridge": self._bridge.health(),
        }
