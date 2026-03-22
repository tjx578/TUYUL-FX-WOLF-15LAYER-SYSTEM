"""
Tests for V11 Gate — input validation, type safety, adapter integration.
"""

import pytest

from analysis.v11.data_adapter import V11DataAdapter
from analysis.v11.extreme_selectivity_gate import ExtremeSelectivityGateV11, V11Thresholds
from analysis.v11.models import GateVerdict, V11GateInput, V11GateResult
from analysis.v11.pipeline_hook import V11PipelineHook

# =====================================================================
# V11GateInput — validation
# =====================================================================


class TestV11GateInput:
    def test_from_dict_empty(self):
        """Empty dict → safe defaults, no crash."""
        inp = V11GateInput.from_dict({})
        assert inp.wolf_score == 0.0
        assert inp.htf_alignment is False
        assert inp.news_clear is True  # default is True (fail-safe: clear)

    def test_from_dict_none(self):
        """None input → safe defaults."""
        inp = V11GateInput.from_dict(None)  # pyright: ignore[reportArgumentType]
        assert inp.wolf_score == 0.0

    def test_from_dict_with_values(self):
        inp = V11GateInput.from_dict(
            {
                "wolf_score": 0.85,
                "tii_score": 0.70,
                "frpc_score": "0.65",  # string → should be coerced to float
                "htf_alignment": True,
                "symbol": "EURUSD",
            }
        )
        assert inp.wolf_score == 0.85
        assert inp.frpc_score == 0.65
        assert inp.htf_alignment is True
        assert inp.symbol == "EURUSD"

    def test_scores_clamped(self):
        """Scores > 1.0 or < 0.0 get clamped."""
        inp = V11GateInput(wolf_score=1.5, tii_score=-0.3)
        assert inp.wolf_score == 1.0
        assert inp.tii_score == 0.0

    def test_invalid_type_raises(self):
        """Non-numeric score raises TypeError."""
        with pytest.raises(TypeError):
            V11GateInput(wolf_score="not_a_number")  # pyright: ignore[reportArgumentType]

    def test_from_dict_garbage_scores_default(self):
        """Garbage values in dict → fall back to 0.0."""
        inp = V11GateInput.from_dict(
            {
                "wolf_score": "garbage",
                "tii_score": None,
                "frpc_score": [1, 2, 3],
            }
        )
        assert inp.wolf_score == 0.0
        assert inp.tii_score == 0.0
        assert inp.frpc_score == 0.0

    def test_frozen(self):
        """V11GateInput is immutable."""
        inp = V11GateInput(wolf_score=0.8)
        with pytest.raises(AttributeError):
            inp.wolf_score = 0.9  # pyright: ignore[reportAttributeAccessIssue]


# =====================================================================
# ExtremeSelectivityGateV11 — evaluation
# =====================================================================


class TestExtremeSelectivityGate:
    def _make_passing_input(self) -> dict:
        return {
            "wolf_score": 0.85,
            "tii_score": 0.75,
            "frpc_score": 0.70,
            "confluence_score": 0.80,
            "htf_alignment": True,
            "session_valid": True,
            "news_clear": True,
            "momentum_confirmed": True,
            "atr_value": 0.0015,
            "spread_ratio": 0.10,
            "symbol": "EURUSD",
            "timeframe": "H1",
        }

    def test_all_passing(self):
        gate = ExtremeSelectivityGateV11()
        result = gate.evaluate(self._make_passing_input())
        assert result.verdict == GateVerdict.PASS
        assert result.passed
        assert result.overall_score > 0.5
        assert len(result.failed_criteria) == 0

    def test_all_failing(self):
        gate = ExtremeSelectivityGateV11()
        result = gate.evaluate({})
        assert result.verdict == GateVerdict.FAIL
        assert not result.passed
        assert len(result.failed_criteria) > 0

    def test_partial_fail(self):
        data = self._make_passing_input()
        data["wolf_score"] = 0.30  # below threshold
        data["htf_alignment"] = False  # fail
        gate = ExtremeSelectivityGateV11()
        result = gate.evaluate(data)
        assert "wolf_score_below_threshold" in result.failed_criteria
        assert "htf_not_aligned" in result.failed_criteria

    def test_custom_thresholds(self):
        loose = V11Thresholds(
            min_wolf_score=0.10,
            min_tii_score=0.10,
            min_frpc_score=0.10,
            min_confluence_score=0.10,
            require_htf_alignment=False,
            require_session_valid=False,
            require_news_clear=False,
            require_momentum=False,
            min_pass_ratio=0.50,
        )
        gate = ExtremeSelectivityGateV11(thresholds=loose)
        result = gate.evaluate(
            {
                "wolf_score": 0.20,
                "tii_score": 0.20,
                "frpc_score": 0.20,
                "confluence_score": 0.20,
                "atr_value": 0.001,
                "spread_ratio": 0.1,
            }
        )
        assert result.verdict == GateVerdict.PASS

    def test_accepts_v11_gate_input_directly(self):
        gate = ExtremeSelectivityGateV11()
        inp = V11GateInput(
            wolf_score=0.90,
            tii_score=0.80,
            frpc_score=0.75,
            confluence_score=0.85,
            htf_alignment=True,
            session_valid=True,
            news_clear=True,
            momentum_confirmed=True,
            atr_value=0.002,
            spread_ratio=0.05,
        )
        result = gate.evaluate(inp)
        assert result.verdict == GateVerdict.PASS

    def test_never_crashes_on_garbage(self):
        """Gate must NEVER crash, even on absurd input."""
        gate = ExtremeSelectivityGateV11()
        for garbage in [None, 42, "string", [], True, {"nested": {"deep": object()}}]:
            result = gate.evaluate(garbage)  # type: ignore
            assert isinstance(result, V11GateResult)
            assert result.verdict in (GateVerdict.FAIL, GateVerdict.SKIP)


# =====================================================================
# V11DataAdapter — pipeline bridge
# =====================================================================


class TestV11DataAdapter:
    def test_flat_dict(self):
        adapter = V11DataAdapter()
        inp = adapter.collect(
            {
                "wolf_score": 0.80,
                "tii_score": 0.70,
                "symbol": "GBPUSD",
            }
        )
        assert isinstance(inp, V11GateInput)
        assert inp.wolf_score == 0.80
        assert inp.symbol == "GBPUSD"

    def test_nested_aliases(self):
        adapter = V11DataAdapter()
        inp = adapter.collect(
            {
                "scores": {"wolf": 0.85, "tii": 0.70, "frpc": 0.65},
                "synthesis": {"confluence_score": 0.75},
                "context": {"htf_alignment": True, "session_valid": True},
                "volatility": {"atr": 0.0012, "spread_ratio": 0.08},
                "pair": "USDJPY",
                "tf": "M15",
            }
        )
        assert inp.wolf_score == 0.85
        assert inp.confluence_score == 0.75
        assert inp.htf_alignment is True
        assert inp.atr_value == 0.0012
        assert inp.symbol == "USDJPY"
        assert inp.timeframe == "M15"

    def test_garbage_input(self):
        adapter = V11DataAdapter()
        inp = adapter.collect("not a dict")  # pyright: ignore[reportArgumentType]
        assert isinstance(inp, V11GateInput)
        assert inp.wolf_score == 0.0


# =====================================================================
# V11PipelineHook — end-to-end
# =====================================================================


class TestV11PipelineHook:
    def test_full_pipeline_pass(self):
        hook = V11PipelineHook()
        result = hook.run(
            {
                "wolf_score": 0.85,
                "tii_score": 0.75,
                "frpc_score": 0.70,
                "confluence_score": 0.80,
                "htf_alignment": True,
                "session_valid": True,
                "news_clear": True,
                "momentum_confirmed": True,
                "atr_value": 0.0015,
                "spread_ratio": 0.10,
                "symbol": "EURUSD",
            }
        )
        assert result.passed

    def test_full_pipeline_fail(self):
        hook = V11PipelineHook()
        result = hook.run({})
        assert not result.passed

    def test_run_and_annotate(self):
        hook = V11PipelineHook()
        data = {"symbol": "EURUSD", "wolf_score": 0.85}
        annotated = hook.run_and_annotate(data)
        assert "v11_gate" in annotated
        assert "verdict" in annotated["v11_gate"]
        assert annotated["symbol"] == "EURUSD"  # original data preserved

    def test_never_crashes(self):
        hook = V11PipelineHook()
        for garbage in [None, 42, "x", [], {}]:
            result = hook.run(garbage)  # type: ignore
            assert isinstance(result, V11GateResult)
