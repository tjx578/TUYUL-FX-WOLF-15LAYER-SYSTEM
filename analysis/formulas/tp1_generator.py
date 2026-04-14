"""TP1 Generator — algorithmic take-profit level computation.

Zone: analysis/formulas/ — pure calculation, no side-effects.

Previously the system only *validated* an externally supplied TP1 against a
minimum risk-reward ratio.  This module **generates** TP1 algorithmically from
price structure data so the pipeline always has a structurally grounded target.

Generation logic (candidate priority, lowest to highest distance from entry):

1. **ATR-based fallback** — entry ± 2 × ATR (simplest, always available).
2. **Swing high / swing low** — nearest structural level above entry (BUY) or
   below entry (SELL) found within the recent candle window.
3. **FVG midpoint** — midpoint of the most recent unfilled Fair Value Gap in
   the trade direction.
4. **Fibonacci extension** — 1.272× and 1.618× projections of the most recent
   swing range.

The generator selects the **nearest candidate that satisfies** ``min_rr``
(default 2.0).  If no structural candidate meets the minimum RR, it falls back
to the pure ATR-based target (which by construction always yields exactly 2.0
RR when ``tp_atr_multiplier == sl_atr_multiplier * 2``).

All inputs / outputs are plain Python types — no Redis, no side-effects.
"""

from __future__ import annotations

from typing import Any

__all__ = ["TP1Generator", "generate_tp1"]

_DEFAULT_MIN_RR: float = 2.0
_SWING_LOOKBACK: int = 3  # candles each side for swing detection
_FVG_LOOKBACK: int = 8  # most-recent N candles to scan for FVG


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_tp1(
    candles: list[dict[str, Any]],
    entry: float,
    sl: float,
    direction: str,
    *,
    min_rr: float = _DEFAULT_MIN_RR,
    atr: float | None = None,
) -> dict[str, Any]:
    """Generate TP1 algorithmically from price structure.

    Parameters
    ----------
    candles:
        Ordered list of OHLCV dicts (oldest first).  Each dict must contain
        ``open``, ``high``, ``low``, ``close`` keys (float).
    entry:
        Trade entry price.
    sl:
        Stop-loss price (must be on the correct side of entry).
    direction:
        ``"BUY"`` or ``"SELL"``.
    min_rr:
        Minimum acceptable risk-reward ratio (default 2.0).
    atr:
        Pre-computed ATR value.  When *None* the generator computes its own
        14-period ATR from *candles*.

    Returns
    -------
    dict with keys:
        ``tp1`` (float), ``source`` (str), ``rr`` (float), ``valid`` (bool),
        ``candidates`` (list of dicts with ``price``, ``source``, ``rr``).
    """
    gen = TP1Generator(min_rr=min_rr)
    return gen.generate(candles=candles, entry=entry, sl=sl, direction=direction, atr=atr)


class TP1Generator:
    """Algorithmic TP1 generator — pure analysis, no side-effects."""

    def __init__(self, *, min_rr: float = _DEFAULT_MIN_RR) -> None:
        self.min_rr = min_rr
        self._structural_zones: dict[str, Any] | None = None

    def set_structural_zones(self, zones: dict[str, Any] | None) -> None:
        """Inject pre-computed structural zones from L3/L9 upstream layers.

        Expected keys (all optional):
            vpc_zones: list[dict] — Volume Profile Clusters from L3
                Each: {"price_low": float, "price_high": float, "strength": float}
            volume_profile_poc: float — Point of Control from L3
            fvg_zones: list[dict] — FVG zones from L9/L3
                Each: {"high": float, "low": float}
            ob_zones: list[dict] — Order Block zones from L9/L3
                Each: {"high": float, "low": float}
            liquidity_levels: list[float] — key liquidity prices from L9
            bos_level: float — Break of Structure level from L9

        This is advisory enrichment — zone candidates are scored alongside
        internally detected candidates, not replacing them.
        """
        self._structural_zones = dict(zones) if zones else None

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def generate(
        self,
        candles: list[dict[str, Any]],
        entry: float,
        sl: float,
        direction: str,
        *,
        atr: float | None = None,
        structural_zones: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate TP1 from multiple structural candidates.

        Returns the nearest valid candidate satisfying ``self.min_rr``.
        Falls back to the ATR-based target when no structural level qualifies.

        If *structural_zones* is provided (from L3/L9), zone-derived candidates
        are added alongside internally detected ones.
        """
        if direction not in {"BUY", "SELL"}:
            return self._fail("invalid_direction")
        if entry <= 0 or sl <= 0:
            return self._fail("invalid_entry_or_sl")

        risk = abs(entry - sl)
        if risk <= 0:
            return self._fail("zero_risk")

        # --- Validate direction consistency ---
        if direction == "BUY" and sl >= entry:
            return self._fail("sl_above_entry_for_buy")
        if direction == "SELL" and sl <= entry:
            return self._fail("sl_below_entry_for_sell")

        # --- ATR ---
        effective_atr = atr if (atr is not None and atr > 0) else _compute_atr(candles)
        if effective_atr <= 0 and len(candles) >= 1:
            last = candles[-1]
            effective_atr = max(last.get("high", 0.0) - last.get("low", 0.0), risk)

        # --- Build candidate list ---
        candidates: list[dict[str, Any]] = []

        # 0. Minimum RR guarantee — always present; no structural dependency
        min_rr_dist = self.min_rr * risk
        min_rr_tp = round(entry + min_rr_dist, 5) if direction == "BUY" else round(entry - min_rr_dist, 5)
        candidates.append({"price": min_rr_tp, "source": "min_rr"})

        # 1. ATR-based (entry ± 2×ATR)
        atr_tp = _atr_tp(entry, effective_atr, direction)
        if atr_tp > 0:
            candidates.append({"price": atr_tp, "source": "atr_2x"})

        # 2. Swing high / low levels
        for level in _swing_levels(candles, direction):
            candidates.append({"price": level, "source": "swing"})

        # 3. FVG midpoints
        for level in _fvg_levels(candles, direction):
            candidates.append({"price": level, "source": "fvg"})

        # 4. Fibonacci extensions
        for price, label in _fib_extensions(candles, entry, direction):
            candidates.append({"price": price, "source": f"fib_{label}"})

        # 5. Upstream structural zones (L3/L9 enrichment)
        zones = structural_zones or self._structural_zones
        if zones:
            candidates.extend(_zone_candidates(zones, entry, direction))

        # --- Score candidates ---
        scored: list[dict[str, Any]] = []
        for c in candidates:
            tp = c["price"]
            if tp <= 0:
                continue
            # Must be on the correct side of entry
            if direction == "BUY" and tp <= entry:
                continue
            if direction == "SELL" and tp >= entry:
                continue
            rr = round(abs(tp - entry) / risk, 2)
            scored.append({"price": round(tp, 5), "source": c["source"], "rr": rr})

        # Filter to min_rr, then pick nearest (smallest distance)
        valid = [c for c in scored if c["rr"] >= self.min_rr]

        if valid:
            chosen = min(valid, key=lambda c: abs(c["price"] - entry))
        elif scored:
            # Fall back to min_rr guarantee candidate if available
            min_rr_candidates = [c for c in scored if c["source"] == "min_rr"]
            chosen = min_rr_candidates[0] if min_rr_candidates else scored[0]
        else:
            return self._fail("no_candidates")

        return {
            "valid": True,
            "tp1": chosen["price"],
            "source": chosen["source"],
            "rr": chosen["rr"],
            "candidates": scored,
            "entry": round(entry, 5),
            "sl": round(sl, 5),
            "direction": direction,
            "atr": round(effective_atr, 5),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fail(reason: str) -> dict[str, Any]:
        return {
            "valid": False,
            "tp1": 0.0,
            "source": "none",
            "rr": 0.0,
            "candidates": [],
            "reason": reason,
        }


# ---------------------------------------------------------------------------
# ATR computation
# ---------------------------------------------------------------------------


def _compute_atr(candles: list[dict[str, Any]], period: int = 14) -> float:
    """Simple 14-period ATR (Wilder average of True Range)."""
    if len(candles) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(candles)):
        h = candles[i].get("high", 0.0)
        lo = candles[i].get("low", 0.0)
        pc = candles[i - 1].get("close", 0.0)
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    if not trs:
        return 0.0
    use = trs[-period:]
    return sum(use) / len(use)


# ---------------------------------------------------------------------------
# ATR-based TP
# ---------------------------------------------------------------------------


def _atr_tp(entry: float, atr: float, direction: str) -> float:
    """Return entry ± 2 × ATR."""
    dist = atr * 2.0
    return round(entry + dist, 5) if direction == "BUY" else round(entry - dist, 5)


# ---------------------------------------------------------------------------
# Swing high / low candidates
# ---------------------------------------------------------------------------


def _swing_levels(candles: list[dict[str, Any]], direction: str) -> list[float]:
    """Return swing highs (BUY) or swing lows (SELL) as TP candidates."""
    if len(candles) < _SWING_LOOKBACK * 2 + 1:
        return []

    highs = [c.get("high", 0.0) for c in candles]
    lows = [c.get("low", 0.0) for c in candles]
    levels: list[float] = []
    n = len(candles)
    k = _SWING_LOOKBACK

    for i in range(k, n - k):
        if direction == "BUY":
            # Swing high: local maximum in the high series
            h = highs[i]
            if (
                h > 0
                and all(h >= highs[i - j] for j in range(1, k + 1))
                and all(h >= highs[i + j] for j in range(1, k + 1))
            ):
                levels.append(round(h, 5))
        else:
            # Swing low: local minimum in the low series
            lo = lows[i]
            if (
                lo > 0
                and all(lo <= lows[i - j] for j in range(1, k + 1))
                and all(lo <= lows[i + j] for j in range(1, k + 1))
            ):
                levels.append(round(lo, 5))

    return levels


# ---------------------------------------------------------------------------
# Fair Value Gap midpoint candidates
# ---------------------------------------------------------------------------


def _fvg_levels(candles: list[dict[str, Any]], direction: str) -> list[float]:
    """Return unfilled FVG midpoints as TP candidates.

    Bullish FVG (target for BUY): high[i] < low[i+2]  → gap above price.
    Bearish FVG (target for SELL): low[i] > high[i+2] → gap below price.
    The midpoint of the gap is returned as a structural magnet.
    """
    if len(candles) < 3:
        return []

    levels: list[float] = []
    scan = candles[-_FVG_LOOKBACK:] if len(candles) >= _FVG_LOOKBACK else candles

    for i in range(len(scan) - 2):
        h0, lo0 = scan[i].get("high", 0.0), scan[i].get("low", 0.0)
        h1, lo1 = scan[i + 1].get("high", 0.0), scan[i + 1].get("low", 0.0)
        h2, lo2 = scan[i + 2].get("high", 0.0), scan[i + 2].get("low", 0.0)

        if direction == "BUY" and h0 < lo2:
            # Bullish FVG: gap between high[0] and low[2], middle candle doesn't fill it
            filled = (lo1 <= h0) and (h1 >= lo2)
            if not filled:
                mid = round((h0 + lo2) / 2.0, 5)
                if mid > 0:
                    levels.append(mid)
        elif direction == "SELL" and lo0 > h2:
            # Bearish FVG: gap between low[0] and high[2]
            filled = (lo1 <= h2) and (h1 >= lo0)
            if not filled:
                mid = round((lo0 + h2) / 2.0, 5)
                if mid > 0:
                    levels.append(mid)

    return levels


# ---------------------------------------------------------------------------
# Fibonacci extension candidates
# ---------------------------------------------------------------------------

_FIB_EXTENSIONS = (("1.272", 1.272), ("1.618", 1.618))


def _fib_extensions(
    candles: list[dict[str, Any]],
    entry: float,
    direction: str,
) -> list[tuple[float, str]]:
    """Return Fibonacci extension targets from the most recent swing range.

    For BUY: projects upward from the most recent swing low using the
    distance to the nearest swing high.
    For SELL: projects downward from the most recent swing high using the
    distance to the nearest swing low.
    """
    if len(candles) < 10:
        return []

    highs = [c.get("high", 0.0) for c in candles[-30:]]
    lows = [c.get("low", 0.0) for c in candles[-30:]]

    swing_high = max(highs)
    swing_low = min(lows)
    rng = swing_high - swing_low
    if rng <= 0:
        return []

    results: list[tuple[float, str]] = []
    for label, ratio in _FIB_EXTENSIONS:
        if direction == "BUY":
            target = round(swing_low + rng * ratio, 5)
            if target > entry:
                results.append((target, label))
        else:
            target = round(swing_high - rng * ratio, 5)
            if target < entry:
                results.append((target, label))

    return results


# ---------------------------------------------------------------------------
# Upstream structural zone candidates (L3 / L9 enrichment)
# ---------------------------------------------------------------------------


def _zone_candidates(
    zones: dict[str, Any],
    entry: float,
    direction: str,
) -> list[dict[str, Any]]:
    """Build TP candidates from pre-computed upstream structural zones.

    Accepts zone data from L3 (VPC, POC) and L9 (FVG, OB, liquidity, BOS).
    Each valid zone midpoint or level becomes a candidate with a source tag
    prefixed with ``l3_`` or ``l9_`` to distinguish from internally detected
    candidates.
    """
    candidates: list[dict[str, Any]] = []

    def _add(price: float, source: str) -> None:
        if price <= 0:
            return
        if direction == "BUY" and price <= entry:
            return
        if direction == "SELL" and price >= entry:
            return
        candidates.append({"price": round(price, 5), "source": source})

    # --- L3: Volume Profile Clusters ---
    for vpc in zones.get("vpc_zones", []):
        if not isinstance(vpc, dict):
            continue
        lo = vpc.get("price_low", 0.0)
        hi = vpc.get("price_high", 0.0)
        if lo > 0 and hi > 0:
            _add((lo + hi) / 2.0, "l3_vpc")

    # --- L3: Volume Profile POC ---
    poc = zones.get("volume_profile_poc", 0.0)
    if isinstance(poc, (int, float)):
        _add(float(poc), "l3_poc")

    # --- L9: FVG zones ---
    for fvg in zones.get("fvg_zones", []):
        if not isinstance(fvg, dict):
            continue
        lo = fvg.get("low", 0.0)
        hi = fvg.get("high", 0.0)
        if lo > 0 and hi > 0:
            _add((lo + hi) / 2.0, "l9_fvg")

    # --- L9: Order Block zones ---
    for ob in zones.get("ob_zones", []):
        if not isinstance(ob, dict):
            continue
        lo = ob.get("low", 0.0)
        hi = ob.get("high", 0.0)
        if lo > 0 and hi > 0:
            _add((lo + hi) / 2.0, "l9_ob")

    # --- L9: Liquidity levels ---
    for level in zones.get("liquidity_levels", []):
        if isinstance(level, (int, float)):
            _add(float(level), "l9_liquidity")

    # --- L9: BOS level ---
    bos = zones.get("bos_level", 0.0)
    if isinstance(bos, (int, float)):
        _add(float(bos), "l9_bos")

    return candidates
