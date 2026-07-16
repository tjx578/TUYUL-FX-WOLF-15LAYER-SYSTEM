"""Step 1 — HTF Daily Phase Feed (flag-guarded, default ON).

Activates the golden matcher's already-written but dormant Daily-aware rules by
populating ``MarketContext.d1_phase``. Pure context — no execution side-effect,
no new BUY_LIMIT_WATCH, no candidate-direction change, Daily is never an entry
trigger. When the flag is OFF, matcher decisions remain legacy-equivalent.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from types import SimpleNamespace

from analysis.market_context_validator import MarketContext
from analysis.signalthrottle_patterns.matcher import match_golden_patterns
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

_FLAG = "HTF_DAILY_PHASE_FEED_ENABLED"


class _FakeResolver:
    """Stands in for HTFStructureSnapshotResolver — returns a fixed daily_bias."""

    def __init__(self, daily_bias: str):
        self._bias = daily_bias

    def resolve(self, _symbol: str):
        return SimpleNamespace(daily_bias=self._bias)


class _BoomResolver:
    def resolve(self, _symbol: str):
        raise RuntimeError("snapshot boom")


def _pipeline(resolver, *, d1_fallback: str | None = "__unset__") -> WolfConstitutionalPipeline:
    p = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    p._htf_snapshot_resolver = resolver
    if d1_fallback != "__unset__":
        # Isolate dispatch logic from the candle bus / _candle_price.
        p._derive_timeframe_phase = lambda _sym, _tf: d1_fallback  # type: ignore[method-assign]
    return p


# --------------------------------------------------------------------------- #
# 1. MarketContext accepts d1_phase but remains backward compatible.
# --------------------------------------------------------------------------- #


def test_marketcontext_d1_phase_default_none_backward_compatible():
    ctx = MarketContext(symbol="GBPNZD", raw_allowed_direction="BUY")
    assert ctx.d1_phase is None  # legacy callers unaffected
    assert "d1_phase" in asdict(ctx)


def test_marketcontext_accepts_explicit_d1_phase():
    ctx = MarketContext(symbol="GBPNZD", raw_allowed_direction="BUY", d1_phase="BEARISH")
    assert ctx.d1_phase == "BEARISH"


# --------------------------------------------------------------------------- #
# 2 + 3. Pipeline fills d1_phase only when the flag is ON.
# --------------------------------------------------------------------------- #


def test_flag_off_returns_none(monkeypatch):
    monkeypatch.setenv(_FLAG, "false")
    # Even with a resolver that *would* yield BEARISH, OFF must yield None.
    p = _pipeline(_FakeResolver("BEARISH"))
    assert p._derive_daily_phase_feed("GBPNZD") is None


def test_default_on_uses_snapshot_daily_bias_as_source_of_truth(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    # Fallback would return FALLBACK; snapshot priority must win.
    p = _pipeline(_FakeResolver("BEARISH"), d1_fallback="FALLBACK")
    assert p._derive_daily_phase_feed("GBPNZD") == "BEARISH"


def test_flag_on_falls_back_to_d1_when_snapshot_no_bias(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline(_FakeResolver("NO_BIAS"), d1_fallback="DOWNTREND")
    assert p._derive_daily_phase_feed("GBPNZD") == "DOWNTREND"


def test_stale_snapshot_is_advisory_and_does_not_fallback_into_hard_phase(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline(_FakeResolver("STALE"), d1_fallback="BULLISH")

    assert p._derive_daily_phase_feed("GBPNZD") is None


# --------------------------------------------------------------------------- #
# 4. Matcher receives d1_phase (dormant Daily rules no longer dead-code).
# --------------------------------------------------------------------------- #


def test_matcher_feature_dict_carries_d1_phase():
    ctx = MarketContext(symbol="EURUSD", raw_allowed_direction="BUY", d1_phase="BEARISH")
    # asdict(context) is the exact mechanism _golden_pattern_features uses.
    features = asdict(ctx)
    assert features["d1_phase"] == "BEARISH"
    features.update(
        {
            "range_position": 0.9,
            "phase_priced": "NEUTRAL",
            "m15_close_pos": 0.5,
            "duration_seconds": 120,
        }
    )

    without_daily = match_golden_patterns({**features, "d1_phase": None})
    with_daily = match_golden_patterns(features)

    assert "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE" not in without_daily["matched_patterns"]
    assert "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE" in with_daily["matched_patterns"]
    assert "late_upper_density_no_chase" in with_daily["pattern_evidence"]


# --------------------------------------------------------------------------- #
# 5. Missing D1 candle / missing snapshot does not crash.
# --------------------------------------------------------------------------- #


def test_snapshot_failure_falls_back_without_crash(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline(_BoomResolver(), d1_fallback="BEARISH")
    assert p._derive_daily_phase_feed("GBPNZD") == "BEARISH"  # swallowed, fell back


def test_no_data_anywhere_returns_none_without_crash(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline(_FakeResolver("NO_BIAS"), d1_fallback=None)
    assert p._derive_daily_phase_feed("GBPNZD") is None


# --------------------------------------------------------------------------- #
# 6. No execution side-effect.
# --------------------------------------------------------------------------- #


def test_no_execution_side_effect(monkeypatch, caplog):
    monkeypatch.setenv(_FLAG, "true")
    p = _pipeline(_FakeResolver("BEARISH"), d1_fallback="FALLBACK")
    with caplog.at_level(logging.WARNING):
        result = p._derive_daily_phase_feed("GBPNZD")
    assert isinstance(result, str)  # str | None only
    # Pure context derivation — emits no signal/execution artifacts.
    assert "SignalJSON" not in caplog.text
    assert "valid_for_execution" not in caplog.text
    # Idempotent read.
    assert p._derive_daily_phase_feed("GBPNZD") == result
