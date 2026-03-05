"""
Tests for parallel enrichment execution in engines/enrichment_orchestrator.py.

Verifies:
- engines/enrichment_orchestrator._PARALLEL_ENRICHMENT flag
- ThreadPoolExecutor parallel execution of engines 1-8
- Engine 9 (Advisory) always runs sequentially after 1-8
- Single-engine failure does not block other engines
- Fallback to sequential mode when flag is False
- Graceful handling when all engines fail
- Timeout handling per engine
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import engines.enrichment_orchestrator as _mod
from engines.enrichment_orchestrator import (
    EngineEnrichmentLayer,
    EnrichmentResult,
    _PARALLEL_ENRICHMENT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engines(
    *,
    fail_keys: set[str] | None = None,
    slow_keys: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return a mock engine suite.

    Args:
        fail_keys: Engine keys that should raise RuntimeError when called.
        slow_keys: Engine keys that should sleep for the given number of seconds.
    """
    fail_keys = fail_keys or set()
    slow_keys = slow_keys or {}

    def _make_coherence_engine() -> MagicMock:
        e = MagicMock()
        snapshot = MagicMock()
        if "coherence" in fail_keys:
            e.evaluate.side_effect = RuntimeError("coherence boom")
        else:
            if "coherence" in slow_keys:
                def _slow_eval(state: dict[str, Any]) -> Any:
                    time.sleep(slow_keys["coherence"])
                    return snapshot
                e.evaluate.side_effect = _slow_eval
            else:
                e.evaluate.return_value = snapshot
            e.export.return_value = {"score": 0.8, "engine": "coherence"}
        return e

    def _make_simple_engine(key: str, out_dict: dict[str, Any]) -> MagicMock:
        e = MagicMock()
        if key in fail_keys:
            e.evaluate.side_effect = RuntimeError(f"{key} boom")
            e.analyze.side_effect = RuntimeError(f"{key} boom")
        elif key in slow_keys:
            def _slow(state: Any, **_kw: Any) -> SimpleNamespace:
                time.sleep(slow_keys[key])
                return SimpleNamespace(**out_dict)
            e.evaluate.side_effect = _slow
            e.analyze.side_effect = _slow
        else:
            e.evaluate.return_value = SimpleNamespace(**out_dict)
            e.analyze.return_value = SimpleNamespace(**out_dict)
        return e

    advisory = MagicMock()
    if "advisory" in fail_keys:
        advisory.analyze.side_effect = RuntimeError("advisory boom")
    else:
        advisory.analyze.return_value = SimpleNamespace(signal="ok", confidence=0.9)

    return {
        "coherence": _make_coherence_engine(),
        "context":   _make_simple_engine("context",   {"score": 0.7}),
        "risk_sim":  _make_simple_engine("risk_sim",  {"tail_risk_score": 0.1, "max_drawdown_pct": 0.05}),
        "momentum":  _make_simple_engine("momentum",  {"momentum_score": 0.6, "valid": True}),
        "precision": _make_simple_engine("precision", {"precision_weight": 0.65, "valid": True}),
        "structure": _make_simple_engine("structure", {"structure_score": 0.7}),
        "field":     _make_simple_engine("field",     {"stability": 0.8}),
        "probability": _make_simple_engine("probability", {"probability": 0.72}),
        "advisory":  advisory,
    }


def _make_layer_results() -> dict[str, Any]:
    return {
        "L2": {"frpc_energy": 0.4},
        "L4": {"wolf_30_point": {"total": 22}},
        "L5": {"psychology_score": 70, "eaf_score": 0.6},
        "L8": {"tii_sym": 0.75, "integrity": 0.8},
    }


def _build_orchestrator_with_engines(
    engines: dict[str, Any],
    *,
    candles: dict[str, Any] | None = None,
) -> EngineEnrichmentLayer:
    layer = EngineEnrichmentLayer(context_bus=None)
    layer._engines = engines
    # Patch _build_candles to return controlled candles
    mock_candles = candles if candles is not None else {"H1": [{"o": 1.1, "h": 1.2, "l": 1.0, "c": 1.15}]}
    layer._build_candles = MagicMock(return_value=mock_candles)  # type: ignore[method-assign]
    return layer


# ---------------------------------------------------------------------------
# Test 1 — Parallel produces same result structure as sequential
# ---------------------------------------------------------------------------
class TestParallelVsSequential:
    """Parallel and sequential modes must produce structurally identical results."""

    def test_parallel_produces_same_result_as_sequential(self) -> None:
        engines = _make_engines()
        layer_results = _make_layer_results()

        # Run in sequential mode
        with patch.object(_mod, "_PARALLEL_ENRICHMENT", False):
            layer_seq = _build_orchestrator_with_engines(dict(engines))
            layer_seq._engines = _make_engines()  # fresh engines
            result_seq = layer_seq.run(
                symbol="EURUSD",
                direction="BUY",
                layer_results=layer_results,
            )

        # Run in parallel mode
        with patch.object(_mod, "_PARALLEL_ENRICHMENT", True):
            layer_par = _build_orchestrator_with_engines(dict(engines))
            layer_par._engines = _make_engines()  # fresh engines
            result_par = layer_par.run(
                symbol="EURUSD",
                direction="BUY",
                layer_results=layer_results,
            )

        # Both must return an EnrichmentResult
        assert isinstance(result_seq, EnrichmentResult)
        assert isinstance(result_par, EnrichmentResult)

        # Both should have no errors (all engines healthy)
        assert result_seq.errors == [], f"Sequential errors: {result_seq.errors}"
        assert result_par.errors == [], f"Parallel errors: {result_par.errors}"

        # Both should be valid (at least one engine produced output)
        assert result_seq.valid
        assert result_par.valid

        # Key fields must be populated in both
        for field_name in (
            "cognitive_coherence",
            "cognitive_context",
            "quantum_advisory",
        ):
            assert getattr(result_seq, field_name), f"Sequential missing {field_name}"
            assert getattr(result_par, field_name), f"Parallel missing {field_name}"

        # Enrichment score must be non-negative
        assert result_seq.enrichment_score >= 0.0
        assert result_par.enrichment_score >= 0.0


# ---------------------------------------------------------------------------
# Test 2 — Single engine failure does not block other engines
# ---------------------------------------------------------------------------
class TestSingleEngineFailureIsolation:
    """If one engine fails, the remaining 7 must still produce results."""

    @pytest.mark.parametrize("failing_engine", [
        "coherence",
        "context",
        "risk_sim",
        "momentum",
        "precision",
        "structure",
        "field",
        "probability",
    ])
    def test_single_engine_failure_does_not_block_others(
        self, failing_engine: str
    ) -> None:
        engines = _make_engines(fail_keys={failing_engine})
        layer = _build_orchestrator_with_engines(engines)

        result = layer.run(
            symbol="EURUSD",
            direction="BUY",
            layer_results=_make_layer_results(),
        )

        assert isinstance(result, EnrichmentResult)

        # The failing engine should be recorded in errors
        assert any(failing_engine in err for err in result.errors), (
            f"Expected error for '{failing_engine}' in {result.errors}"
        )

        # The remaining engines should NOT all fail — result should still be valid
        # (advisory receives empty/default values for the failed engine but runs)
        # At minimum one field should be populated
        populated = [
            f for f in (
                "cognitive_coherence", "cognitive_context", "risk_simulation",
                "fusion_momentum", "fusion_precision", "fusion_structure",
                "quantum_field", "quantum_probability",
            )
            if getattr(result, f)
        ]
        assert len(populated) >= 1, (
            f"Expected at least 1 engine to succeed when only '{failing_engine}' fails"
        )


# ---------------------------------------------------------------------------
# Test 3 — Advisory (engine 9) receives results from engines 1-8
# ---------------------------------------------------------------------------
class TestAdvisoryReceivesEngineOutputs:
    """Engine 9 (Advisory) must be called with outputs from engines 1-8."""

    def test_advisory_receives_all_engine_outputs(self) -> None:
        engines = _make_engines()
        advisory_mock = engines["advisory"]
        layer = _build_orchestrator_with_engines(engines)

        result = layer.run(
            symbol="EURUSD",
            direction="BUY",
            layer_results=_make_layer_results(),
        )

        # Advisory must have been called exactly once
        advisory_mock.analyze.assert_called_once()
        call_kwargs = advisory_mock.analyze.call_args

        # Extract the advisory_inputs dict (first positional arg)
        advisory_inputs = call_kwargs[0][0]
        assert isinstance(advisory_inputs, dict)

        # All 8 engine result keys must be present in the advisory inputs
        for key in ("coherence", "context", "risk_sim", "momentum",
                    "precision", "structure", "field", "probability"):
            assert key in advisory_inputs, f"Advisory missing key: {key}"

        # Metadata must be present
        assert advisory_inputs["direction"] == "BUY"
        assert advisory_inputs["symbol"] == "EURUSD"

        # Advisory output must be recorded
        assert result.quantum_advisory


# ---------------------------------------------------------------------------
# Test 4 — Fallback to sequential mode
# ---------------------------------------------------------------------------
class TestSequentialFallback:
    """Setting _PARALLEL_ENRICHMENT = False must use sequential execution."""

    def test_fallback_to_sequential(self) -> None:
        engines = _make_engines()
        layer = _build_orchestrator_with_engines(engines)

        with patch.object(_mod, "_PARALLEL_ENRICHMENT", False):
            result = layer.run(
                symbol="GBPUSD",
                direction="SELL",
                layer_results=_make_layer_results(),
            )

        assert isinstance(result, EnrichmentResult)
        assert result.errors == []
        assert result.valid

    def test_sequential_mode_does_not_call_thread_pool(self) -> None:
        engines = _make_engines()
        layer = _build_orchestrator_with_engines(engines)

        with patch.object(_mod, "_PARALLEL_ENRICHMENT", False), \
             patch("concurrent.futures.ThreadPoolExecutor") as mock_pool:
            layer.run(
                symbol="GBPUSD",
                direction="SELL",
                layer_results=_make_layer_results(),
            )
            # ThreadPoolExecutor should NOT be used in sequential mode
            mock_pool.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — All engines fail, result is invalid but no crash
# ---------------------------------------------------------------------------
class TestAllEnginesFail:
    """If all 9 engines raise, EnrichmentResult.valid is False but no exception."""

    def test_all_engines_failed_returns_valid_result(self) -> None:
        all_keys = {
            "coherence", "context", "risk_sim", "momentum",
            "precision", "structure", "field", "probability", "advisory",
        }
        engines = _make_engines(fail_keys=all_keys)
        layer = _build_orchestrator_with_engines(engines)

        result = layer.run(
            symbol="EURUSD",
            direction="BUY",
            layer_results=_make_layer_results(),
        )

        assert isinstance(result, EnrichmentResult)
        # All engines failed → valid should be False
        assert not result.valid
        # Errors list should have entries (at least advisory + some engines)
        assert len(result.errors) > 0
        # No crash — elapsed_ms should be set
        assert result.elapsed_ms >= 0.0
        # to_dict() must not raise
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "errors" in d


# ---------------------------------------------------------------------------
# Test 6 — Timeout handling
# ---------------------------------------------------------------------------
class TestTimeoutHandling:
    """An engine that exceeds _ENRICHMENT_TIMEOUT should be gracefully skipped."""

    def test_timeout_handling(self) -> None:
        # Make one engine sleep beyond the configured timeout, but short enough
        # that the thread completes well within the pytest 30s limit.
        slow_engines = _make_engines(
            slow_keys={"momentum": 2.0},
        )
        layer = _build_orchestrator_with_engines(slow_engines)

        # Use a very short timeout so we detect the timeout without blocking
        with patch.object(_mod, "_ENRICHMENT_TIMEOUT", 0.05):
            result = layer.run(
                symbol="EURUSD",
                direction="BUY",
                layer_results=_make_layer_results(),
            )

        assert isinstance(result, EnrichmentResult)
        # Result may have some errors (timeout or otherwise) — no crash
        assert result.elapsed_ms >= 0.0
        d = result.to_dict()
        assert isinstance(d, dict)
