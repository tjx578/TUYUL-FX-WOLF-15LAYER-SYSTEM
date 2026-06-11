"""Increment H1 — HTF Structure Snapshot tests.

Covers the pure structure primitives, the snapshot builder/resolver, and the
flag-guarded emitter.  The over-arching contract under test is the H1 safety
invariant: the snapshot is *never* executable and BUY pressure is *never*
auto-promoted to a BUY LIMIT.
"""

from __future__ import annotations

import logging

from analysis.htf_structure_snapshot import (
    BIAS_BEARISH,
    BIAS_BULLISH,
    BIAS_NO_BIAS,
    BIAS_RANGE,
    BIAS_TRANSITION,
    ENABLE_ENV,
    EVENT_NAME,
    H4_BEARISH_PULLBACK,
    H4_BULLISH_PULLBACK,
    LIQ_BUY_SIDE,
    LIQ_SELL_SIDE,
    LOC_DISCOUNT,
    LOC_PREMIUM,
    HTFStructureSnapshot,
    HTFStructureSnapshotResolver,
    build_snapshot,
    classify_bias,
    classify_liquidity_context,
    classify_price_location,
    dealing_range,
    emit_htf_structure_snapshot,
    find_swing_highs,
    find_swing_lows,
    resolve_playbook,
)

# --------------------------------------------------------------------------- #
# Candle factories
# --------------------------------------------------------------------------- #


def _c(high: float, low: float, close: float | None = None, open_: float | None = None) -> dict[str, float]:
    close = close if close is not None else (high + low) / 2
    open_ = open_ if open_ is not None else close
    return {"open": open_, "high": high, "low": low, "close": close}


def _zigzag(pivots: list[float], eps: float = 0.15, fill: int = 2) -> list[dict[str, float]]:
    """Build candles tracing a zig-zag through ``pivots``.

    ``fill`` ramp bars are inserted between consecutive pivots so each pivot is
    a strictly-dominant fractal extreme over a ``window=2`` neighbourhood.
    """
    closes: list[float] = []
    prev = pivots[0]
    for level in pivots:
        for s in range(1, fill + 1):
            closes.append(prev + (level - prev) * s / (fill + 1))
        closes.append(level)
        prev = level
    return [_c(x + eps, x - eps, close=x) for x in closes]


def _staircase_up(n: int = 24, step: float = 1.0, base: float = 100.0) -> list[dict[str, float]]:
    """Ascending zig-zag with Higher-Highs + Higher-Lows -> BULLISH."""
    lows = [base + i * 2 * step for i in range(4)]
    highs = [base + 3 * step + i * 2 * step for i in range(4)]
    pivots: list[float] = []
    for lo, hi in zip(lows, highs, strict=False):
        pivots.extend((lo, hi))
    return _zigzag(pivots)


def _staircase_down(n: int = 24, step: float = 1.0, base: float = 100.0) -> list[dict[str, float]]:
    """Descending zig-zag with Lower-Highs + Lower-Lows -> BEARISH."""
    highs = [base - i * 2 * step for i in range(4)]
    lows = [base - 3 * step - i * 2 * step for i in range(4)]
    pivots: list[float] = []
    for hi, lo in zip(highs, lows, strict=False):
        pivots.extend((hi, lo))
    return _zigzag(pivots)


# --------------------------------------------------------------------------- #
# §1  Swing detection
# --------------------------------------------------------------------------- #


def test_swing_detection_finds_peaks_and_valleys():
    candles = [_c(h, low) for h, low in [(5, 1), (6, 2), (10, 3), (6, 2), (4, 1), (3, 0), (7, 2), (3, 1)]]
    highs = find_swing_highs(candles, window=2)
    lows = find_swing_lows(candles, window=2)
    assert any(s.price == 10 for s in highs)
    assert any(s.price == 0 for s in lows)


# --------------------------------------------------------------------------- #
# §2  Bias classification matrix
# --------------------------------------------------------------------------- #


def test_bias_bullish_from_hh_hl():
    candles = _staircase_up()
    assert classify_bias(find_swing_highs(candles), find_swing_lows(candles)) == BIAS_BULLISH


def test_bias_bearish_from_lh_ll():
    candles = _staircase_down()
    assert classify_bias(find_swing_highs(candles), find_swing_lows(candles)) == BIAS_BEARISH


def test_bias_no_bias_when_insufficient_swings():
    assert classify_bias([], []) == BIAS_NO_BIAS


def test_bias_transition_on_expansion():
    from analysis.htf_structure_snapshot import Swing

    # HH (higher high) + LL (lower low) = expanding range -> TRANSITION
    highs = [Swing(2, 10.0), Swing(6, 12.0)]
    lows = [Swing(4, 5.0), Swing(8, 3.0)]
    assert classify_bias(highs, lows) == BIAS_TRANSITION


def test_bias_range_on_contraction():
    from analysis.htf_structure_snapshot import Swing

    # LH + HL = contraction -> RANGE
    highs = [Swing(2, 12.0), Swing(6, 10.0)]
    lows = [Swing(4, 3.0), Swing(8, 5.0)]
    assert classify_bias(highs, lows) == BIAS_RANGE


# --------------------------------------------------------------------------- #
# §3  Location + liquidity
# --------------------------------------------------------------------------- #


def test_dealing_range_high_low():
    candles = [_c(10, 4), _c(12, 5), _c(11, 3)]
    assert dealing_range(candles, 10) == (12, 3)


def test_price_location_premium_and_discount():
    rng = (120.0, 100.0)
    assert classify_price_location(118.0, rng, None, None) == LOC_PREMIUM
    assert classify_price_location(102.0, rng, None, None) == LOC_DISCOUNT


def test_price_location_h4_supply_at_premium_extreme():
    rng = (120.0, 100.0)
    # close at premium AND hugging the H4 swing high -> H4_SUPPLY
    loc = classify_price_location(119.0, rng, h4_swing_high=119.5, h4_swing_low=101.0)
    assert loc == "H4_SUPPLY"


def test_liquidity_buy_side_near_high():
    assert classify_liquidity_context(119.0, (120.0, 100.0)) == LIQ_BUY_SIDE


def test_liquidity_sell_side_near_low():
    assert classify_liquidity_context(101.0, (120.0, 100.0)) == LIQ_SELL_SIDE


# --------------------------------------------------------------------------- #
# §4  Playbook guardrail — BUY pressure is never an auto BUY LIMIT
# --------------------------------------------------------------------------- #


def test_bearish_daily_blocks_buy_limit():
    allowed, blocked = resolve_playbook(BIAS_BEARISH, LOC_PREMIUM)
    assert allowed == "SELL_ON_REJECTION"
    assert "BUY_LIMIT" in blocked
    assert "BUY_BREAKOUT_CHASE" in blocked


def test_bullish_daily_blocks_sell_limit():
    allowed, blocked = resolve_playbook(BIAS_BULLISH, LOC_DISCOUNT)
    assert allowed == "BUY_ON_REJECTION"
    assert "SELL_LIMIT" in blocked


def test_transition_blocks_both_limits():
    _allowed, blocked = resolve_playbook(BIAS_TRANSITION, "EQUILIBRIUM")
    assert "BUY_LIMIT" in blocked and "SELL_LIMIT" in blocked


def test_no_bias_blocks_everything_structural():
    _allowed, blocked = resolve_playbook(BIAS_NO_BIAS, "UNKNOWN")
    assert {"BUY_LIMIT", "SELL_LIMIT", "BUY_BREAKOUT_CHASE", "SELL_BREAKOUT_CHASE"} <= set(blocked)


def test_range_fades_extremes_blocks_breakout_chase():
    allowed, blocked = resolve_playbook(BIAS_RANGE, LOC_PREMIUM)
    assert allowed == "RANGE_FADE_EXTREME"
    assert "BUY_BREAKOUT_CHASE" in blocked and "SELL_BREAKOUT_CHASE" in blocked


# --------------------------------------------------------------------------- #
# §5  Snapshot builder — end-to-end + the hard non-executable invariant
# --------------------------------------------------------------------------- #


def test_snapshot_is_never_executable():
    snap = build_snapshot("GBPNZD", _staircase_down(), _staircase_down())
    d = snap.to_dict()
    assert d["valid_for_execution"] is False
    assert d["is_final_signal"] is False
    assert d["event"] == EVENT_NAME


def test_snapshot_bearish_blocks_buy_limit_end_to_end():
    # Daily downtrend with price parked high in the range -> SELL bias, BUY_LIMIT blocked
    daily = _staircase_down(n=30, base=160.0)
    h4 = _staircase_down(n=30, base=132.0)
    snap = build_snapshot("GBPNZD", daily, h4)
    assert snap.daily_bias == BIAS_BEARISH
    assert "BUY_LIMIT" in snap.blocked_playbook
    assert snap.valid_for_execution is False


def test_snapshot_insufficient_daily_is_no_bias_and_locked():
    snap = build_snapshot("EURUSD", daily=[_c(2, 1)] * 3, h4=_staircase_up())
    assert snap.daily_bias == BIAS_NO_BIAS
    assert snap.data_sufficient is False
    assert snap.valid_for_execution is False
    assert "BUY_LIMIT" in snap.blocked_playbook and "SELL_LIMIT" in snap.blocked_playbook


def test_snapshot_degraded_h4_still_reads_daily():
    snap = build_snapshot("EURUSD", daily=_staircase_up(), h4=[_c(2, 1)] * 4)
    assert snap.daily_bias == BIAS_BULLISH
    assert snap.data_sufficient is False  # h4 too short
    assert snap.h4_structure == "NO_STRUCTURE"


def test_h4_structure_pullback_labels_present():
    # Just assert the labels are reachable string constants (wiring sanity).
    assert H4_BULLISH_PULLBACK == "BULLISH_PULLBACK"
    assert H4_BEARISH_PULLBACK == "BEARISH_PULLBACK"


# --------------------------------------------------------------------------- #
# §6  Resolver with an injected candle source
# --------------------------------------------------------------------------- #


class _FakeBus:
    def __init__(self, data: dict[str, list[dict[str, float]]]):
        self._data = data

    def get_candle_history(self, symbol, timeframe, count=None):
        rows = self._data.get(f"{symbol}:{timeframe}", [])
        if count is not None and count < len(rows):
            return rows[-count:]
        return rows


def test_resolver_reads_daily_and_h4_from_source():
    bus = _FakeBus(
        {
            "GBPNZD:D1": _staircase_down(n=30, base=160.0),
            "GBPNZD:H4": _staircase_down(n=30, base=132.0),
        }
    )
    snap = HTFStructureSnapshotResolver(candle_source=bus).resolve("gbpnzd")
    assert snap.symbol == "GBPNZD"
    assert snap.daily_bias == BIAS_BEARISH
    assert snap.valid_for_execution is False


def test_resolver_no_source_is_no_bias_locked():
    snap = HTFStructureSnapshotResolver(candle_source=_FakeBus({})).resolve("EURUSD")
    assert snap.daily_bias == BIAS_NO_BIAS
    assert snap.valid_for_execution is False


# --------------------------------------------------------------------------- #
# §7  Flag-guarded emit (default OFF)
# --------------------------------------------------------------------------- #


def _snap() -> HTFStructureSnapshot:
    return build_snapshot("GBPNZD", _staircase_down(n=30, base=160.0), _staircase_down(n=30, base=132.0))


def test_emit_off_by_default(monkeypatch, caplog):
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    with caplog.at_level(logging.WARNING):
        emitted = emit_htf_structure_snapshot(_snap())
    assert emitted is False
    assert "[HTFStructureSnapshot]" not in caplog.text


def test_emit_on_when_flag_set(monkeypatch, caplog):
    monkeypatch.setenv(ENABLE_ENV, "true")
    with caplog.at_level(logging.WARNING):
        emitted = emit_htf_structure_snapshot(_snap())
    assert emitted is True
    assert "[HTFStructureSnapshot]" in caplog.text
    assert f'"event":"{EVENT_NAME}"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
    assert '"is_final_signal":false' in caplog.text


def test_emit_explicit_enabled_overrides_env(monkeypatch, caplog):
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    with caplog.at_level(logging.WARNING):
        emitted = emit_htf_structure_snapshot(_snap(), enabled=True)
    assert emitted is True
    assert "[HTFStructureSnapshot]" in caplog.text


def test_emit_none_is_noop():
    assert emit_htf_structure_snapshot(None, enabled=True) is False


def test_build_event_reasserts_safety_lock_on_loose_dict():
    from analysis.htf_structure_snapshot import build_htf_structure_snapshot_event

    payload = build_htf_structure_snapshot_event({"symbol": "X", "valid_for_execution": True})
    assert payload["valid_for_execution"] is False
    assert payload["is_final_signal"] is False
    assert payload["event"] == EVENT_NAME
