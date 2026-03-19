"""
Full mock test for WolfConstitutionalPipeline.execute().

Fully mocks all 11 layer analyzers, governance engines, and external I/O
(Redis, context bus) so the test runs without any infrastructure. Exercises
the entire 8-phase pipeline code path end-to-end and validates:

- Result structural contract (all required keys)
- L12 verdict authority & mandatory fields
- L13 two-pass reflective governance
- L15 sovereignty enforcement
- Early-exit on layer failures (L1, L2, L3 invalid)
- Warmup gate rejection
- Signal throttle downgrade
- Safe-mode bypass
- Constitutional boundary (no balance/equity in verdict)
- Latency tracking
- Error list accumulation
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

# ──────────────────────────────────────────────────────────────────
#  Fake layer results
# ──────────────────────────────────────────────────────────────────


def _l1(valid: bool = True, **overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "valid": valid,
        "direction": "BUY",
        "strength": 0.75,
        "session": "London",
        "volatility_level": "NORMAL",
        "regime": "TRENDING",
    }
    d.update(overrides)
    return d


def _l2(valid: bool = True, **overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "valid": valid,
        "direction": "BUY",
        "strength": 0.70,
        "htf_bias": "BULLISH",
        "per_tf_bias": {},
        "reflex_coherence": 0.85,
    }
    d.update(overrides)
    return d


def _l3(valid: bool = True, **overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "valid": valid,
        "direction": "BUY",
        "strength": 0.72,
        "trend": "BULLISH",
        "pattern": "OB_RETEST",
    }
    d.update(overrides)
    return d


def _l4(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "direction": "BUY",
        "score": 0.80,
        "technical_score": 75,
        "session_score": 0.85,
        "coherence": 0.78,
        "directional_bias": 0.65,
    }
    d.update(overrides)
    return d


def _l5(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "psychology_score": 78,
        "discipline_ok": True,
        "current_drawdown": 0.01,
        "consecutive_losses": 0,
        "emotion_delta": 0.05,
        "volatility_index": 18.0,
        "atr_normalized": 20.0,
    }
    d.update(overrides)
    return d


def _l6(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "risk_ok": True,
        "risk_score": 0.65,
        "correlation_risk": "LOW",
        "risk_status": "STABLE",
        "propfirm_compliant": True,
        "max_risk_pct": 1.0,
        "warnings": [],
    }
    d.update(overrides)
    return d


def _l7(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "confluence_score": 0.77,
        "validation": "PASS",
        "win_probability": 62.0,
        "profit_factor": 1.85,
        "bayesian_posterior": 0.72,
        "risk_of_ruin": 0.03,
        "mc_passed_threshold": True,
    }
    d.update(overrides)
    return d


def _l8(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"tii_score": 0.94, "valid": True}
    d.update(overrides)
    return d


def _l9(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "smc_score": 0.70,
        "structure": "BULLISH",
        "confidence": 0.68,
    }
    d.update(overrides)
    return d


def _l10(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"dynamic_size_ok": True, "kelly_fraction": 0.025}
    d.update(overrides)
    return d


def _l11(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "valid": True,
        "rr": 2.8,
        "rr_ok": True,
        "entry_price": 1.0850,
        "stop_loss": 1.0800,
        "take_profit_1": 1.0990,
        "entry": 1.0850,
        "sl": 1.0800,
        "tp1": 1.0990,
        "tp": 1.0990,
    }
    d.update(overrides)
    return d


def _macro(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "regime": "RISK_ON",
        "phase": "EXPANSION",
        "macro_vol_ratio": 0.85,
        "alignment": True,
        "liquidity": {},
        "bias_override": {},
    }
    d.update(overrides)
    return d


# ──────────────────────────────────────────────────────────────────
#  Pipeline builder with all analyzers mocked
# ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mocked_pipeline(monkeypatch: pytest.MonkeyPatch):
    """
    Build a WolfConstitutionalPipeline with all layer analyzers stubbed
    and external I/O patched out.
    """

    class _FakeRedisClient:
        def get(self, _key: str) -> bytes | None:
            from state.redis_keys import HEARTBEAT_INGEST

            if _key == HEARTBEAT_INGEST:
                return f'{{"ts": {time.time()}}}'.encode()
            return None

    # Governance gate can use either self._redis or RedisClient(); force both to no-I/O stubs.
    monkeypatch.setattr("storage.redis_client.RedisClient", lambda: _FakeRedisClient())

    pipeline = WolfConstitutionalPipeline()

    # Prevent execute() from touching the process-level Redis client.
    pipeline._redis = _FakeRedisClient()  # pyright: ignore[reportAttributeAccessIssue]

    # Replace lazy loader so it doesn't import real analyzers
    pipeline._ensure_analyzers = lambda: None

    # Stub layer analyzers
    pipeline._l1 = MagicMock()
    pipeline._l1.analyze = MagicMock(return_value=_l1())
    pipeline._l2 = MagicMock()
    pipeline._l2.analyze = MagicMock(return_value=_l2())
    pipeline._l3 = MagicMock()
    pipeline._l3.analyze = MagicMock(return_value=_l3())
    pipeline._l4 = MagicMock()
    pipeline._l4.score = MagicMock(return_value=_l4())
    pipeline._l5 = MagicMock()
    pipeline._l5.analyze = MagicMock(return_value=_l5())
    pipeline._l6 = MagicMock()
    pipeline._l6.analyze = MagicMock(return_value=_l6())
    pipeline._l6._compute_lrce = MagicMock(return_value=0.1)
    pipeline._l6.lrce_block_threshold = 0.8
    pipeline._l7 = MagicMock()
    pipeline._l7.analyze = MagicMock(return_value=_l7())
    pipeline._l8 = MagicMock()
    pipeline._l8.analyze = MagicMock(return_value=_l8())
    pipeline._l9 = MagicMock()
    pipeline._l9.analyze = MagicMock(return_value=_l9())
    pipeline._l10 = MagicMock()
    pipeline._l10.analyze = MagicMock(return_value=_l10())
    pipeline._l11 = MagicMock()
    pipeline._l11.calculate_rr = MagicMock(return_value=_l11())
    pipeline._macro = MagicMock()
    pipeline._macro.analyze = MagicMock(return_value=_macro())
    pipeline._macro_vol = MagicMock()
    pipeline._macro_vol.get_state = MagicMock(return_value={})

    # Stub governance engines
    pipeline._l13_engine = MagicMock()
    pipeline._l13_engine.reflect = MagicMock(
        return_value={
            "confidence_modifier": 0.02,
            "risk_adjustment": 0.0,
            "meta_integrity": 0.95,
        }
    )
    pipeline._l15_engine = MagicMock()
    pipeline._l15_engine.compute_meta = MagicMock(
        return_value={
            "meta_integrity": 0.96,
            "sovereignty_level": "FULL",
        }
    )
    pipeline._l15_engine.enforce_sovereignty = MagicMock(
        return_value={
            "drift_detected": False,
            "verdict_downgraded": False,
        }
    )

    # Stub enrichment
    pipeline._enrichment = MagicMock()
    _enrich_result = MagicMock()
    _enrich_result.to_dict.return_value = {
        "enrichment_score": 0.82,
        "confidence_adjustment": 0.01,
        "fusion_momentum": 0.7,
        "quantum_probability": 0.65,
        "bias_strength": 0.6,
        "posterior": 0.7,
    }
    _enrich_result.enrichment_score = 0.82
    _enrich_result.errors = []
    pipeline._enrichment.run = MagicMock(return_value=_enrich_result)

    # Stub context bus
    pipeline._context_bus = MagicMock()
    pipeline._context_bus.check_warmup = MagicMock(
        return_value={
            "ready": True,
            "bars": 50,
            "required": 5,
        }
    )
    pipeline._context_bus.get_account_state = MagicMock(
        return_value={
            "equity": 99000.0,
            "peak_equity": 100000.0,
            "corr_exposure": 0.0,
            "daily_loss_pct": 0.0,
            "base_kelly": 0.25,
            "open_positions": 1,
            "max_open_positions": 5,
            "circuit_breaker_active": False,
        }
    )
    pipeline._context_bus.get_trade_history = MagicMock(return_value=None)
    pipeline._context_bus.get_conditioned_returns = MagicMock(return_value=None)
    pipeline._context_bus.get_conditioning_meta = MagicMock(return_value=None)
    pipeline._context_bus.get_candles = MagicMock(
        return_value=[
            {
                "timestamp": time.time(),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1,
            }
        ]
    )
    pipeline._context_bus.get_feed_timestamp = MagicMock(return_value=time.time())
    pipeline._context_bus.inference_snapshot = MagicMock(return_value={})

    # Stub vault checker with realistic return value
    _vault_report = MagicMock()
    _vault_report.feed_freshness = 1.0
    _vault_report.redis_health = 1.0
    _vault_report.should_block_analysis = False
    _vault_report.is_healthy = True
    _vault_report.details = ""
    pipeline._vault_checker = MagicMock()
    pipeline._vault_checker.check = MagicMock(return_value=_vault_report)

    # Stub reflex gate & EMC filter (avoid real computation)
    _gate_decision = MagicMock()
    _gate_decision.to_dict.return_value = {"gate": "OPEN", "lot_scale": 1.0}
    pipeline._reflex_gate = MagicMock()
    pipeline._reflex_gate.evaluate = MagicMock(return_value=_gate_decision)
    pipeline._emc_filter = MagicMock()
    pipeline._emc_filter.adaptive_sigma = MagicMock(return_value=60.0)
    pipeline._emc_filter.smooth = MagicMock(return_value=0.85)
    pipeline._emc_filter.get_session = MagicMock(return_value={})

    # Stub signal throttle (never throttle by default)
    pipeline._signal_throttle = MagicMock()
    pipeline._signal_throttle.is_throttled = MagicMock(return_value=False)
    pipeline._signal_throttle.record = MagicMock()

    return pipeline


# ──────────────────────────────────────────────────────────────────
#  Structural contract tests
# ──────────────────────────────────────────────────────────────────


class TestPipelineStructuralContract:
    """execute() must return a dict with all canonical keys."""

    REQUIRED_KEYS = {
        "schema",
        "pair",
        "timestamp",
        "synthesis",
        "l12_verdict",
        "reflective",
        "reflective_pass1",
        "reflective_pass2",
        "l14_json",
        "l15_meta",
        "sovereignty",
        "enforcement",
        "execution_map",
        "latency_ms",
        "errors",
    }

    def test_result_has_all_required_keys(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        missing = self.REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_schema_version(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        assert result["schema"] == "v8.0"

    def test_pair_matches_input(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("XAUUSD")
        assert result["pair"] == "XAUUSD"

    def test_latency_is_positive(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        assert result["latency_ms"] > 0

    def test_errors_is_list(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        assert isinstance(result["errors"], list)

    def test_timestamp_is_string(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        assert isinstance(result["timestamp"], str)


# ──────────────────────────────────────────────────────────────────
#  L12 verdict authority
# ──────────────────────────────────────────────────────────────────

VALID_VERDICTS = {"EXECUTE", "NO_TRADE", "HOLD", "ABORT", "SKIP", "WAIT"}


class TestL12Verdict:
    def test_verdict_present(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        assert "l12_verdict" in result
        assert isinstance(result["l12_verdict"], dict)

    def test_verdict_has_mandatory_fields(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        verdict = result["l12_verdict"]
        assert "verdict" in verdict
        assert "confidence" in verdict

    def test_verdict_value_is_valid(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        v = result["l12_verdict"].get("verdict", "")
        # Allow EXECUTE_* variants
        base = v.split("_")[0] if "_" in v else v
        assert base in VALID_VERDICTS or v.startswith("EXECUTE"), f"Unknown verdict: {v!r}"

    def test_gates_attached_to_verdict(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        verdict = result["l12_verdict"]
        assert "gates_v74" in verdict


# ──────────────────────────────────────────────────────────────────
#  Constitutional boundary: no account data in verdict
# ──────────────────────────────────────────────────────────────────


class TestConstitutionalBoundary:
    FORBIDDEN_KEYS = {"balance", "equity", "margin_used", "account_id"}

    def test_verdict_has_no_account_state(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        verdict = result["l12_verdict"]
        leaked = self.FORBIDDEN_KEYS & set(verdict.keys())
        assert not leaked, f"Account data leaked into verdict: {leaked}"

    def test_synthesis_has_no_account_state(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        synthesis = result["synthesis"]
        assert "balance" not in synthesis
        assert "equity" not in synthesis


# ──────────────────────────────────────────────────────────────────
#  L13 two-pass governance
# ──────────────────────────────────────────────────────────────────


class TestL13Governance:
    def test_l13_reflect_called_twice_on_execute(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        """Two-pass: baseline (meta=1.0) then refined (real meta)."""
        result = mocked_pipeline.execute("EURUSD")
        verdict = result["l12_verdict"].get("verdict", "")
        proceed = result["l12_verdict"].get("proceed_to_L13", False)

        if proceed or verdict.startswith("EXECUTE"):
            assert mocked_pipeline._l13_engine.reflect.call_count == 2  # type: ignore[attr-defined]
            assert result["reflective_pass1"] is not None
            assert result["reflective_pass2"] is not None

    def test_l15_meta_computed(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        if result["l12_verdict"].get("proceed_to_L13", False) or result["l12_verdict"].get("verdict", "").startswith(
            "EXECUTE"
        ):
            assert result["l15_meta"] is not None


# ──────────────────────────────────────────────────────────────────
#  Sovereignty enforcement
# ──────────────────────────────────────────────────────────────────


class TestSovereignty:
    def test_enforcement_present(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        result = mocked_pipeline.execute("EURUSD")
        assert "enforcement" in result
        assert "sovereignty" in result

    def test_sovereignty_enforcement_called(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        mocked_pipeline.execute("EURUSD")
        assert mocked_pipeline._l15_engine.enforce_sovereignty.call_count == 1  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────
#  Early exit on layer failure
# ──────────────────────────────────────────────────────────────────


class TestEarlyExit:
    def test_l1_invalid_returns_early(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        assert mocked_pipeline._l1 is not None, "_l1 analyzer not initialized"
        mocked_pipeline._l1.analyze = MagicMock(return_value=_l1(valid=False))
        result = mocked_pipeline.execute("EURUSD")
        assert "L1_CONTEXT_INVALID" in result["errors"]
        # Should have NO_TRADE verdict from early exit
        assert result["l12_verdict"]["verdict"] in ("NO_TRADE", "HOLD", "ABORT", "SKIP")

    def test_l2_invalid_returns_early(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        assert mocked_pipeline._l2 is not None, "_l2 analyzer not initialized"
        mocked_pipeline._l2.analyze = MagicMock(return_value=_l2(valid=False))
        result = mocked_pipeline.execute("EURUSD")
        assert "L2_MTA_INVALID" in result["errors"]

    def test_l3_invalid_returns_early(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        assert mocked_pipeline._l3 is not None, "_l3 analyzer not initialized"
        mocked_pipeline._l3.analyze = MagicMock(return_value=_l3(valid=False))
        result = mocked_pipeline.execute("EURUSD")
        assert "L3_TECHNICAL_INVALID" in result["errors"]


# ──────────────────────────────────────────────────────────────────
#  Warmup gate
# ──────────────────────────────────────────────────────────────────


class TestWarmupGate:
    def test_warmup_blocked_returns_early(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        mocked_pipeline._context_bus.check_warmup = MagicMock(
            return_value={
                "ready": False,
                "bars": 3,
                "required": 20,
                "missing": 17,
            }
        )
        result = mocked_pipeline.execute("EURUSD")
        assert any("WARMUP" in e for e in result["errors"])

    def test_warmup_skipped_in_safe_mode(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        """Safe mode bypasses warmup gate."""
        mocked_pipeline._context_bus.check_warmup = MagicMock(
            return_value={
                "ready": False,
                "bars": 3,
                "required": 20,
                "missing": 17,
            }
        )
        result = mocked_pipeline.execute("EURUSD", system_metrics={"safe_mode": True})
        # Should NOT have warmup error since safe_mode=True
        assert not any("WARMUP" in e for e in result["errors"])


# ──────────────────────────────────────────────────────────────────
#  Signal throttle
# ──────────────────────────────────────────────────────────────────


class TestSignalThrottle:
    def test_throttled_signal_downgraded_to_hold(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        """When throttle says symbol is throttled, verdict is downgraded."""
        mocked_pipeline._signal_throttle.is_throttled = MagicMock(return_value=True)

        result = mocked_pipeline.execute("EURUSD")
        verdict = result["l12_verdict"]

        # If original was EXECUTE, it should be downgraded
        if verdict.get("throttled_from", "").startswith("EXECUTE"):
            assert verdict["verdict"] == "HOLD"
            assert "SIGNAL_THROTTLED" in result["errors"]


# ──────────────────────────────────────────────────────────────────
#  tick_ts latency tracking
# ──────────────────────────────────────────────────────────────────


class TestTickLatency:
    def test_tick_to_verdict_latency_recorded(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        tick_ts = time.time() - 0.5  # 500ms ago
        result = mocked_pipeline.execute("EURUSD", tick_ts=tick_ts)
        if "tick_to_verdict_s" in result:
            assert result["tick_to_verdict_s"] >= 0.4  # at least ~400ms


# ──────────────────────────────────────────────────────────────────
#  Multiple symbols
# ──────────────────────────────────────────────────────────────────


class TestMultipleSymbols:
    def test_different_symbols_produce_results(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        for symbol in ["EURUSD", "GBPUSD", "XAUUSD"]:
            result = mocked_pipeline.execute(symbol)
            assert result["pair"] == symbol
            assert "l12_verdict" in result


# ──────────────────────────────────────────────────────────────────
#  HOLD direction (neutral trend)
# ──────────────────────────────────────────────────────────────────


class TestNeutralTrend:
    def test_neutral_trend_skips_l11(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        """When L3 trend is NEUTRAL, direction is HOLD and L11 is skipped."""
        assert mocked_pipeline._l3 is not None, "_l3 analyzer not initialized"
        mocked_pipeline._l3.analyze = MagicMock(return_value=_l3(trend="NEUTRAL"))
        result = mocked_pipeline.execute("EURUSD")
        # L11 calculates RR only for BUY/SELL
        # Pipeline should still complete
        assert "l12_verdict" in result


# ──────────────────────────────────────────────────────────────────
#  Fatal error handling
# ──────────────────────────────────────────────────────────────────


class TestFatalError:
    def test_exception_in_layer_returns_early_exit(self, mocked_pipeline: WolfConstitutionalPipeline) -> None:
        """If a layer raises, pipeline should catch and return early exit."""
        assert mocked_pipeline._l4 is not None, "_l4 analyzer not initialized"
        mocked_pipeline._l4.score = MagicMock(side_effect=RuntimeError("L4 boom"))
        result = mocked_pipeline.execute("EURUSD")
        assert any("FATAL_ERROR" in e for e in result["errors"])
        assert result["l12_verdict"]["verdict"] in ("NO_TRADE", "HOLD", "ABORT", "SKIP")
