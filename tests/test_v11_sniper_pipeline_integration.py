"""
V11 Sniper Filter Hook — Pipeline Integration Tests.

The V11 Extreme Selectivity Gate acts as a "sniper filter": it blocks candidates
that score below the extreme-selectivity bar, even if they passed the basic L12 gate.

This file focuses on:
  1. Hook integration with realistic WolfConstitutionalPipeline synthesis outputs
  2. Sniper filter decision accuracy: PASS only best setups, FAIL marginal ones
  3. Annotation contract: pipeline data flow with v11_gate key
  4. Edge cases: missing fields, partial synthesis, garbage data
  5. Non-regression: hook never crashes on any input type

Note: Basic unit tests (V11GateInput, ExtremeSelectivityGateV11, V11DataAdapter)
are in tests/test_v11_gate.py.  This file focuses on the pipeline integration layer.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from analysis.v11.models import GateVerdict, V11GateResult
from analysis.v11.pipeline_hook import V11PipelineHook

# ──────────────────────────────────────────────────────────────────────────────
# Realistic synthesis dict fixtures (matches WolfConstitutionalPipeline output)
# ──────────────────────────────────────────────────────────────────────────────


def _sniper_grade_synthesis(symbol: str = "EURUSD", tf: str = "H1") -> dict[str, Any]:
    """
    Synthesis dict that represents a top-tier setup.
    Should PASS the V11 sniper filter.
    Modelled after the actual build_l12_synthesis() output format.
    """
    return {
        "pair": symbol,
        "timeframe": tf,
        # Flat scores (also accepted by data adapter)
        "wolf_score": 0.88,
        "tii_score": 0.82,
        "frpc_score": 0.76,
        "confluence_score": 0.81,
        "htf_alignment": True,
        "session_valid": True,
        "news_clear": True,
        "momentum_confirmed": True,
        "atr_value": 0.0018,
        "spread_ratio": 0.09,
        # Full scores block (nested format for data adapter)
        "scores": {
            "wolf": 0.88,
            "tii": 0.82,
            "frpc": 0.76,
            "fta_score": 0.85,
            "wolf_30_point": 26,
        },
        # Synthesis meta
        "bias": "BULLISH",
        "direction": "BUY",
        "entry_price": 1.0872,
        "stop_loss": 1.0820,
        "take_profit_1": 1.0972,
        "risk_reward": 1.92,
    }


def _marginal_synthesis(symbol: str = "EURUSD") -> dict[str, Any]:
    """
    Synthesis dict for a marginal setup — satisfies basic L12 but below V11 bar.
    Should FAIL the V11 sniper filter.
    """
    return {
        "pair": symbol,
        "wolf_score": 0.55,
        "tii_score": 0.50,
        "frpc_score": 0.48,
        "confluence_score": 0.52,
        "htf_alignment": False,
        "session_valid": True,
        "news_clear": True,
        "momentum_confirmed": False,
        "atr_value": 0.0010,
        "spread_ratio": 0.22,
        "scores": {
            "wolf": 0.55,
            "tii": 0.50,
            "frpc": 0.48,
            "fta_score": 0.58,
            "wolf_30_point": 17,
        },
        "bias": "NEUTRAL",
        "direction": "BUY",
    }


def _l12_execute_verdict() -> dict[str, Any]:
    """Minimal L12 EXECUTE verdict that gets passed to V11 alongside synthesis."""
    return {
        "symbol": "EURUSD",
        "verdict": "EXECUTE",
        "confidence": 0.78,
        "direction": "BUY",
        "entry_price": 1.0872,
        "stop_loss": 1.0820,
        "take_profit_1": 1.0972,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. Sniper filter decision accuracy
# ──────────────────────────────────────────────────────────────────────────────


class TestV11SniperDecision:
    """V11 must correctly PASS elite setups and FAIL marginal ones."""

    def test_sniper_grade_setup_passes(self):
        """Top-tier synthesis must pass the extreme selectivity gate."""
        hook = V11PipelineHook()
        result = hook.run(_sniper_grade_synthesis())
        assert result.passed, f"Sniper-grade setup should PASS. Failed criteria: {result.failed_criteria}"
        assert result.verdict == GateVerdict.PASS

    def test_marginal_setup_fails(self):
        """Marginal synthesis (below V11 bar) must be blocked."""
        hook = V11PipelineHook()
        result = hook.run(_marginal_synthesis())
        assert not result.passed, "Marginal setup should FAIL the V11 sniper filter"
        assert result.verdict == GateVerdict.FAIL

    def test_pass_has_high_overall_score(self):
        """A passing setup must have overall_score >= 0.5."""
        hook = V11PipelineHook()
        result = hook.run(_sniper_grade_synthesis())
        assert result.overall_score >= 0.5

    def test_fail_has_at_least_one_failed_criterion(self):
        """A failing result must report what failed."""
        hook = V11PipelineHook()
        result = hook.run(_marginal_synthesis())
        assert len(result.failed_criteria) > 0

    def test_sniper_grade_eurusd_and_gbpusd(self):
        """Sniper filter must work for multiple symbols."""
        hook = V11PipelineHook()
        for symbol in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD"):
            result = hook.run(_sniper_grade_synthesis(symbol=symbol))
            assert result.passed, f"Sniper-grade {symbol} should PASS"

    def test_marginal_eurusd_and_gbpusd(self):
        """Marginal filter must block for all symbols."""
        hook = V11PipelineHook()
        for symbol in ("EURUSD", "GBPUSD"):
            result = hook.run(_marginal_synthesis(symbol=symbol))
            assert not result.passed, f"Marginal {symbol} should FAIL"

    def test_sniper_on_h4_timeframe(self):
        """Sniper filter should work on H4 setups (higher timeframe)."""
        hook = V11PipelineHook()
        synthesis = _sniper_grade_synthesis(tf="H4")
        result = hook.run(synthesis)
        assert result.passed


# ──────────────────────────────────────────────────────────────────────────────
# 2. Pipeline synthesis dict integration (nested format)
# ──────────────────────────────────────────────────────────────────────────────


class TestV11NestedSynthesisFormat:
    """
    Data adapter must correctly extract scores from nested dict format
    (as produced by build_l12_synthesis and WolfConstitutionalPipeline).
    """

    def test_nested_scores_block_extracted(self):
        """Scores nested under 'scores' key must be extracted correctly."""
        hook = V11PipelineHook()
        synthesis = {
            "scores": {"wolf": 0.85, "tii": 0.80, "frpc": 0.75},
            "confluence_score": 0.80,
            "htf_alignment": True,
            "session_valid": True,
            "news_clear": True,
            "momentum_confirmed": True,
            "atr_value": 0.0015,
            "spread_ratio": 0.10,
        }
        result = hook.run(synthesis)
        assert result.passed, f"Nested format should resolve to PASS: {result.failed_criteria}"

    def test_nested_context_block_extracted(self):
        """Context nested under 'context' key must be extracted (alternate format)."""
        hook = V11PipelineHook()
        synthesis = {
            "scores": {"wolf": 0.87, "tii": 0.81, "frpc": 0.77},
            "synthesis": {"confluence_score": 0.82},
            "context": {
                "htf_alignment": True,
                "session_valid": True,
                "news_clear": True,
                "momentum_confirmed": True,
            },
            "volatility": {"atr": 0.0016, "spread_ratio": 0.08},
            "pair": "GBPUSD",
            "tf": "H1",
        }
        result = hook.run(synthesis)
        assert result.passed

    def test_flat_and_nested_scores_flat_wins(self):
        """
        If both flat wolf_score and nested scores.wolf exist,
        the adapter should resolve them consistently (no crash, no exception).
        """
        hook = V11PipelineHook()
        synthesis = {
            "wolf_score": 0.90,
            "scores": {"wolf": 0.50},  # conflicting; adapter picks one
            "tii_score": 0.80,
            "frpc_score": 0.75,
            "confluence_score": 0.80,
            "htf_alignment": True,
            "session_valid": True,
            "news_clear": True,
            "momentum_confirmed": True,
            "atr_value": 0.0015,
            "spread_ratio": 0.10,
        }
        # Must not crash; verdict can go either way
        result = hook.run(synthesis)
        assert isinstance(result, V11GateResult)

    def test_synthesis_with_l12_verdict_combined(self):
        """
        Pipeline may pass synthesis + l12 verdict combined in a single dict.
        The hook must not confuse verdict fields with score fields.
        """
        hook = V11PipelineHook()
        combined = {**_sniper_grade_synthesis(), **_l12_execute_verdict()}
        result = hook.run(combined)
        assert result.passed


# ──────────────────────────────────────────────────────────────────────────────
# 3. run_and_annotate() — annotation contract
# ──────────────────────────────────────────────────────────────────────────────


class TestV11AnnotationContract:
    """
    run_and_annotate() must inject 'v11_gate' key and preserve original data.
    This is the primary integration point used by the pipeline.
    """

    def test_annotation_key_injected(self):
        """v11_gate must be present in annotated output."""
        hook = V11PipelineHook()
        annotated = hook.run_and_annotate(_sniper_grade_synthesis())
        assert "v11_gate" in annotated

    def test_annotation_verdict_field_present(self):
        """v11_gate must contain 'verdict' field."""
        hook = V11PipelineHook()
        annotated = hook.run_and_annotate(_sniper_grade_synthesis())
        assert "verdict" in annotated["v11_gate"]

    def test_annotation_overall_score_present(self):
        """v11_gate must contain 'overall_score' field."""
        hook = V11PipelineHook()
        annotated = hook.run_and_annotate(_sniper_grade_synthesis())
        assert "overall_score" in annotated["v11_gate"]

    def test_annotation_passed_field_is_bool(self):
        """v11_gate['passed'] must be a boolean."""
        hook = V11PipelineHook()
        annotated = hook.run_and_annotate(_sniper_grade_synthesis())
        assert isinstance(annotated["v11_gate"]["passed"], bool)

    def test_annotation_failed_criteria_is_list(self):
        """v11_gate['failed_criteria'] must be a list."""
        hook = V11PipelineHook()
        annotated = hook.run_and_annotate(_sniper_grade_synthesis())
        assert isinstance(annotated["v11_gate"]["failed_criteria"], list)

    def test_original_data_preserved(self):
        """Original synthesis fields must not be altered or removed."""
        hook = V11PipelineHook()
        synthesis = _sniper_grade_synthesis()
        original_keys = set(synthesis.keys())
        annotated = hook.run_and_annotate(synthesis)

        for key in original_keys:
            assert key in annotated, f"Key {key!r} was lost during annotation"
            assert annotated[key] == synthesis[key], f"Key {key!r} was modified during annotation"

    def test_annotation_does_not_mutate_original(self):
        """run_and_annotate must not mutate the input dict."""
        hook = V11PipelineHook()
        synthesis = _sniper_grade_synthesis()
        synthesis_copy = dict(synthesis)
        hook.run_and_annotate(synthesis)
        assert synthesis == synthesis_copy, "Input dict was mutated by run_and_annotate"

    def test_annotation_on_failing_setup(self):
        """Annotation must work correctly even for FAIL verdicts."""
        hook = V11PipelineHook()
        annotated = hook.run_and_annotate(_marginal_synthesis())
        assert annotated["v11_gate"]["passed"] is False
        assert annotated["v11_gate"]["verdict"] == GateVerdict.FAIL.value

    def test_annotation_on_empty_dict(self):
        """Empty synthesis dict must produce FAIL annotation without crash."""
        hook = V11PipelineHook()
        annotated = hook.run_and_annotate({})
        assert "v11_gate" in annotated
        assert annotated["v11_gate"]["passed"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 4. Sniper filter blocks marginal L12 EXECUTE signals
# ──────────────────────────────────────────────────────────────────────────────


class TestV11AsSniperLayer:
    """
    Simulate the pipeline flow: L12 says EXECUTE, V11 acts as final sniper gate.
    V11 can override EXECUTE → blocked if setup is not sniper-grade.
    """

    def test_execute_signal_sniper_grade_passes_through(self):
        """EXECUTE signal with sniper-grade scores flows through V11."""
        hook = V11PipelineHook()
        # Simulate pipeline data after L12 gate passed
        pipeline_data = {
            **_l12_execute_verdict(),
            **_sniper_grade_synthesis(),
        }
        result = hook.run(pipeline_data)
        # V11 says PASS → execution can proceed
        assert result.passed

    def test_execute_signal_marginal_blocked_by_v11(self):
        """EXECUTE signal with marginal scores is blocked by V11 sniper filter."""
        hook = V11PipelineHook()
        pipeline_data = {
            **_l12_execute_verdict(),  # L12 says EXECUTE...
            **_marginal_synthesis(),  # ...but V11 disagrees
        }
        result = hook.run(pipeline_data)
        # V11 says FAIL → candidate must be blocked
        assert not result.passed

    def test_no_trade_signal_still_evaluated(self):
        """V11 evaluates NO_TRADE signals too (for journaling/analytics)."""
        hook = V11PipelineHook()
        no_trade_data = {
            "symbol": "EURUSD",
            "verdict": "NO_TRADE",
            "confidence": 0.35,
            **_marginal_synthesis(),
        }
        result = hook.run(no_trade_data)
        assert isinstance(result, V11GateResult)

    def test_v11_does_not_override_verdict_field(self):
        """
        V11 hook must NOT modify the 'verdict' field of the original signal.
        It only annotates — decision power belongs to L12 and pipeline.
        """
        hook = V11PipelineHook()
        pipeline_data = {**_l12_execute_verdict(), **_sniper_grade_synthesis()}
        annotated = hook.run_and_annotate(pipeline_data)

        # Original L12 verdict must be unchanged
        assert annotated["verdict"] == "EXECUTE", "V11 hook must not overwrite the L12 verdict field"

    def test_v11_result_has_no_execution_side_effects(self):
        """V11GateResult must not contain order, lot, or balance fields."""
        hook = V11PipelineHook()
        result = hook.run(_sniper_grade_synthesis())
        result_dict = result.__dict__ if hasattr(result, "__dict__") else {}
        forbidden = {"lot_size", "order_id", "balance", "equity", "place_order"}
        leaked = forbidden & set(result_dict.keys())
        assert not leaked, f"V11 result contained execution fields: {leaked}"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Resilience / never-crash guarantee
# ──────────────────────────────────────────────────────────────────────────────


class TestV11HookResilience:
    """V11PipelineHook must never raise — it returns FAIL/SKIP on bad input."""

    @pytest.mark.parametrize(
        "garbage",
        [
            None,
            42,
            "string",
            [],
            True,
            b"bytes",
            {"nested": {"deep": object()}},
            {i: i for i in range(100)},  # large dict
        ],
    )
    def test_run_never_crashes(self, garbage):
        hook = V11PipelineHook()
        result = hook.run(garbage)
        assert isinstance(result, V11GateResult)
        assert result.verdict in (GateVerdict.FAIL, GateVerdict.SKIP)

    @pytest.mark.parametrize("garbage", [None, 42, [], "x"])
    def test_run_and_annotate_never_crashes(self, garbage):
        hook = V11PipelineHook()
        result = hook.run_and_annotate(garbage)
        assert isinstance(result, dict)
        assert "v11_gate" in result

    def test_hook_with_internal_gate_error_returns_fail(self):
        """If gate.evaluate raises internally, hook must catch and return FAIL."""
        hook = V11PipelineHook()
        with patch.object(hook._gate, "evaluate", side_effect=RuntimeError("gate crash")):
            result = hook.run({"wolf_score": 0.9})
            assert result.verdict == GateVerdict.FAIL
            assert "internal_error" in result.failed_criteria

    def test_hook_with_adapter_error_returns_fail(self):
        """If adapter.collect raises internally, hook must catch and return FAIL."""
        hook = V11PipelineHook()
        with patch.object(hook._adapter, "collect", side_effect=ValueError("adapter err")):
            result = hook.run({"wolf_score": 0.9})
            assert result.verdict == GateVerdict.FAIL

    def test_hook_is_stateless_across_calls(self):
        """
        Two sequential calls must not share state.
        Passing a bad call first must not affect the next good call.
        """
        hook = V11PipelineHook()
        hook.run(None)  # type: ignore[arg-type]  # garbage call
        result = hook.run(_sniper_grade_synthesis())
        assert result.passed, "Stateless: hook must pass a good setup after a garbage call"


# ──────────────────────────────────────────────────────────────────────────────
# 6. Custom threshold configuration (CI smoke)
# ──────────────────────────────────────────────────────────────────────────────


class TestV11ThresholdConfiguration:
    """Verify hook respects custom thresholds passed at construction."""

    def test_strict_threshold_blocks_normal_sniper_grade(self):
        """Ultra-strict thresholds should block even good setups."""
        from analysis.v11.extreme_selectivity_gate import V11Thresholds  # noqa: PLC0415

        extreme = V11Thresholds(
            min_wolf_score=0.99,
            min_tii_score=0.99,
            min_frpc_score=0.99,
            min_confluence_score=0.99,
            min_pass_ratio=1.0,
        )
        hook = V11PipelineHook(thresholds=extreme)
        result = hook.run(_sniper_grade_synthesis())
        assert not result.passed

    def test_loose_threshold_passes_marginal_setup(self):
        """Very loose thresholds should pass even marginal setups."""
        from analysis.v11.extreme_selectivity_gate import V11Thresholds  # noqa: PLC0415

        loose = V11Thresholds(
            min_wolf_score=0.10,
            min_tii_score=0.10,
            min_frpc_score=0.10,
            min_confluence_score=0.10,
            require_htf_alignment=False,
            require_session_valid=False,
            require_news_clear=False,
            require_momentum=False,
            min_pass_ratio=0.40,
        )
        hook = V11PipelineHook(thresholds=loose)
        result = hook.run(_marginal_synthesis())
        assert result.passed
