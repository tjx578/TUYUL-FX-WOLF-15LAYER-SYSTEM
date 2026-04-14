"""Tests for Weekly Context Injection — macro narrative integration in L4 + LiveContextBus."""

from __future__ import annotations

from typing import Any

from analysis.layers.L4_session_scoring import L4ScoringEngine, L4SessionScoring

# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _l1(bias: str = "BULLISH", confidence: float = 0.8) -> dict[str, Any]:
    return {
        "bias": bias,
        "confidence": confidence,
        "strength": 0.7,
        "regime": "TREND_UP",
        "context_coherence": 0.8,
        "volatility_level": "NORMAL",
    }


def _l2() -> dict[str, Any]:
    return {
        "trend_strength": 0.7,
        "momentum": 0.6,
        "rsi": 55,
        "structure_score": 0.65,
        "volume_score": 0.5,
        "trend_bias": "BULLISH",
        "reflex_coherence": 0.7,
    }


def _l3() -> dict[str, Any]:
    return {
        "confidence": 0.7,
        "structure_score": 0.65,
        "rr_ratio": 2.5,
        "technical_score": 70,
    }


def _macro_context(
    *,
    weekly_bias: dict[str, str] | str | None = None,
    risk_sentiment: str = "RISK_ON",
    macro_themes: list[str] | None = None,
    calendar_events: list[str] | None = None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {"risk_sentiment": risk_sentiment}
    if weekly_bias is not None:
        ctx["weekly_bias"] = weekly_bias
    if macro_themes is not None:
        ctx["macro_themes"] = macro_themes
    if calendar_events is not None:
        ctx["calendar_events"] = calendar_events
    return ctx


# ---------------------------------------------------------------------------
# Tests: L4SessionScoring macro narrative
# ---------------------------------------------------------------------------

class TestL4MacroNarrative:

    def test_no_macro_context_returns_unavailable(self) -> None:
        """Without macro injection, macro_narrative.available is False."""
        engine = L4SessionScoring()
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="EURUSD")
        mn = result["macro_narrative"]
        assert mn["available"] is False
        assert mn["risk_sentiment"] == "UNKNOWN"
        assert mn["bias_alignment"] == "UNKNOWN"

    def test_macro_context_available_after_injection(self) -> None:
        """After set_macro_context(), macro_narrative is available."""
        engine = L4SessionScoring()
        engine.set_macro_context(_macro_context(
            weekly_bias={"EUR": "BULLISH", "USD": "BEARISH"},
            risk_sentiment="RISK_ON",
        ))
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="EURUSD")
        mn = result["macro_narrative"]
        assert mn["available"] is True
        assert mn["risk_sentiment"] == "RISK_ON"

    def test_aligned_buy_when_base_bullish_quote_bearish(self) -> None:
        """Base BULLISH + Quote BEARISH → ALIGNED_BUY."""
        engine = L4SessionScoring()
        engine.set_macro_context(_macro_context(
            weekly_bias={"EUR": "BULLISH", "USD": "BEARISH"},
        ))
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="EURUSD")
        assert result["macro_narrative"]["bias_alignment"] == "ALIGNED_BUY"

    def test_aligned_sell_when_base_bearish_quote_bullish(self) -> None:
        """Base BEARISH + Quote BULLISH → ALIGNED_SELL."""
        engine = L4SessionScoring()
        engine.set_macro_context(_macro_context(
            weekly_bias={"NZD": "BEARISH", "CAD": "BULLISH"},
        ))
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="NZDCAD")
        assert result["macro_narrative"]["bias_alignment"] == "ALIGNED_SELL"

    def test_neutral_when_same_bias(self) -> None:
        """Both currencies same bias → NEUTRAL."""
        engine = L4SessionScoring()
        engine.set_macro_context(_macro_context(
            weekly_bias={"GBP": "BULLISH", "JPY": "BULLISH"},
        ))
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="GBPJPY")
        assert result["macro_narrative"]["bias_alignment"] == "NEUTRAL"

    def test_mixed_when_partial_bias(self) -> None:
        """One BULLISH, one NEUTRAL → MIXED."""
        engine = L4SessionScoring()
        engine.set_macro_context(_macro_context(
            weekly_bias={"AUD": "BULLISH", "USD": "NEUTRAL"},
        ))
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="AUDUSD")
        assert result["macro_narrative"]["bias_alignment"] == "MIXED"

    def test_macro_themes_propagated(self) -> None:
        """Macro themes are passed through to output."""
        engine = L4SessionScoring()
        themes = ["USD_strength_on_Fed_hold", "EUR_PMI_weak"]
        engine.set_macro_context(_macro_context(macro_themes=themes))
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="EURUSD")
        assert result["macro_narrative"]["macro_themes"] == themes

    def test_calendar_events_counted(self) -> None:
        """Calendar events are counted (not passed raw)."""
        engine = L4SessionScoring()
        events = ["FOMC rate decision", "ECB speech", "NFP"]
        engine.set_macro_context(_macro_context(calendar_events=events))
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="EURUSD")
        assert result["macro_narrative"]["events_this_week"] == 3

    def test_wolf_30_point_unchanged_by_macro(self) -> None:
        """Macro narrative must NOT alter Wolf 30-Point scores."""
        engine = L4SessionScoring()

        # Without macro
        result_no_macro = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="EURUSD")
        wolf_no = result_no_macro["wolf_30_point"]["total"]

        # With macro
        engine.set_macro_context(_macro_context(
            weekly_bias={"EUR": "BULLISH", "USD": "BEARISH"},
            risk_sentiment="RISK_ON",
        ))
        result_macro = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="EURUSD")
        wolf_macro = result_macro["wolf_30_point"]["total"]

        assert wolf_no == wolf_macro

    def test_empty_macro_context_treated_as_unavailable(self) -> None:
        """Empty dict injection → available=False."""
        engine = L4SessionScoring()
        engine.set_macro_context({})
        result = engine.analyze(l1=_l1(), l2=_l2(), l3=_l3(), pair="EURUSD")
        assert result["macro_narrative"]["available"] is False


# ---------------------------------------------------------------------------
# Tests: L4ScoringEngine wrapper propagation
# ---------------------------------------------------------------------------

class TestL4ScoringEngineWrapper:

    def test_set_macro_context_propagates(self) -> None:
        """L4ScoringEngine.set_macro_context() reaches inner engine."""
        wrapper = L4ScoringEngine()
        wrapper.set_macro_context(_macro_context(
            weekly_bias={"EUR": "BULLISH", "USD": "BEARISH"},
        ))
        assert wrapper._inner._macro_context.get("weekly_bias") == {
            "EUR": "BULLISH", "USD": "BEARISH",
        }


# ---------------------------------------------------------------------------
# Tests: LiveContextBus macro narrative storage
# ---------------------------------------------------------------------------

class TestLiveContextBusMacroNarrative:

    def _make_bus(self) -> Any:
        """Create a fresh LiveContextBus instance (bypassing singleton)."""
        from context.live_context_bus import LiveContextBus

        bus = object.__new__(LiveContextBus)
        bus._init()
        return bus

    def test_get_macro_narrative_empty_default(self) -> None:
        """Without update, returns empty dict."""
        bus = self._make_bus()
        assert bus.get_macro_narrative() == {}

    def test_update_and_get_macro_narrative(self) -> None:
        """update_macro_narrative() stores and get retrieves."""
        bus = self._make_bus()
        narrative = {
            "weekly_bias": {"EUR": "BULLISH"},
            "risk_sentiment": "RISK_ON",
            "macro_themes": ["USD_weakness"],
        }
        bus.update_macro_narrative(narrative)
        result = bus.get_macro_narrative()
        assert result["weekly_bias"] == {"EUR": "BULLISH"}
        assert result["risk_sentiment"] == "RISK_ON"

    def test_get_returns_copy_not_reference(self) -> None:
        """Returned narrative must be a copy (no mutation of internal state)."""
        bus = self._make_bus()
        bus.update_macro_narrative({"key": "value"})
        result = bus.get_macro_narrative()
        result["injected"] = True
        assert "injected" not in bus.get_macro_narrative()

    def test_inference_snapshot_includes_macro_narrative(self) -> None:
        """inference_snapshot() must include the macro_narrative field."""
        bus = self._make_bus()
        bus.update_macro_narrative({"risk_sentiment": "RISK_OFF"})
        snap = bus.inference_snapshot()
        assert "macro_narrative" in snap
        assert snap["macro_narrative"]["risk_sentiment"] == "RISK_OFF"
