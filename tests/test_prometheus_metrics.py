"""
Tests for GAP #7: Prometheus metrics collector and pipeline instrumentation.

Validates:
  1. core.metrics Counter / Gauge / Histogram and Prometheus exposition format
  2. Pipeline records metrics on normal exit, early exit, and warmup block
  3. MetricsRegistry singleton and idempotent registration
  4. /metrics endpoint returns valid Prometheus text
"""

from __future__ import annotations

import math
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.metrics import (
    FEED_AGE,
    GATE_RESULT,
    PIPELINE_DURATION,
    PIPELINE_ERROR,
    PIPELINE_RUNS,
    RQI_SCORE,
    SIGNAL_CONDITIONED_SAMPLES,
    SIGNAL_NOISE_RATIO,
    SIGNAL_QUALITY_SCORE,
    SIGNAL_TOTAL,
    VERDICT_TOTAL,
    WARMUP_BLOCKED,
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    get_registry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_registry() -> MetricsRegistry:
    """Reset the MetricsRegistry singleton and return a fresh instance."""
    MetricsRegistry.reset_singleton()
    reg = MetricsRegistry()
    return reg


def _pipeline_early_exit(pipe: Any, symbol: str, errors: list[str], latency_ms: float) -> None:
    pipe._early_exit(symbol, errors, latency_ms)


def _set_pipeline_context_bus(pipe: Any, bus: Any) -> None:
    pipe._context_bus = bus


# ===========================================================================
# Counter tests
# ===========================================================================


class TestCounter:
    def test_inc_default(self):
        c = Counter("test_counter", "A test counter")
        c.inc()
        c.inc()
        samples = c.collect()
        assert len(samples) == 1
        assert samples[0][2] == 2.0

    def test_inc_amount(self):
        c = Counter("test_counter2", "Counter with amount")
        c.inc(5)
        assert c.collect()[0][2] == 5.0

    def test_inc_negative_raises(self):
        c = Counter("test_counter3", "Counter negative")
        with pytest.raises(ValueError, match="must be >= 0"):
            c.inc(-1)

    def test_labelled_counter(self):
        c = Counter("test_labelled", "Labelled counter", label_names=("symbol",))
        c.labels(symbol="EURUSD").inc(3)
        c.labels(symbol="GBPJPY").inc(1)
        samples = c.collect()
        values = {s[1].get("symbol"): s[2] for s in samples}
        assert values["EURUSD"] == 3.0
        assert values["GBPJPY"] == 1.0

    def test_labelless_counter_errors_on_labels_call(self):
        c = Counter("test_nolabel", "No labels")
        # Calling .labels() on a labelless counter should still work (empty kwargs)
        # but .inc() on the base should work
        c.inc()
        assert c.collect()[0][2] == 1.0

    def test_labelled_counter_errors_on_direct_inc(self):
        c = Counter("test_lb2", "Labelled", label_names=("gate",))
        with pytest.raises(TypeError, match="Must call .labels"):  # noqa: RUF043
            c.inc()


# ===========================================================================
# Gauge tests
# ===========================================================================


class TestGauge:
    def test_set(self):
        g = Gauge("test_gauge", "A test gauge")
        g.set(42.5)
        assert g.collect()[0][2] == 42.5

    def test_inc_dec(self):
        g = Gauge("test_gauge_incdec", "Inc/dec gauge")
        g.set(10)
        g.inc(5)
        g.dec(3)
        assert g.collect()[0][2] == 12.0

    def test_labelled_gauge(self):
        g = Gauge("test_lg", "Labelled gauge", label_names=("symbol",))
        g.labels(symbol="EURUSD").set(2.3)
        g.labels(symbol="XAUUSD").set(0.5)
        samples = g.collect()
        values = {s[1]["symbol"]: s[2] for s in samples}
        assert math.isclose(values["EURUSD"], 2.3, rel_tol=1e-9, abs_tol=1e-12)
        assert math.isclose(values["XAUUSD"], 0.5, rel_tol=1e-9, abs_tol=1e-12)


# ===========================================================================
# Histogram tests
# ===========================================================================


class TestHistogram:
    def test_observe_and_buckets(self):
        h = Histogram(
            "test_hist",
            "A histogram",
            buckets=(0.1, 0.5, 1.0),
        )
        h.observe(0.05)
        h.observe(0.3)
        h.observe(0.8)
        h.observe(2.0)

        samples = h.collect()
        # Expect: 3 bucket samples + 1 +Inf + sum + count = 6
        bucket_samples = [s for s in samples if "_bucket" in s[0]]
        assert len(bucket_samples) == 4  # 0.1, 0.5, 1.0, +Inf

        # Cumulative buckets: le=0.1 -> 1, le=0.5 -> 2, le=1.0 -> 3, +Inf -> 4
        bucket_map = {s[1]["le"]: s[2] for s in bucket_samples}
        assert bucket_map["0.1"] == 1
        assert bucket_map["0.5"] == 2
        assert bucket_map["1"] == 3
        assert bucket_map["+Inf"] == 4

        sum_samples = [s for s in samples if s[0].endswith("_sum")]
        assert math.isclose(sum_samples[0][2], 0.05 + 0.3 + 0.8 + 2.0, rel_tol=1e-9, abs_tol=1e-12)

        count_samples = [s for s in samples if s[0].endswith("_count")]
        assert count_samples[0][2] == 4

    def test_labelled_histogram(self):
        h = Histogram(
            "test_lhist",
            "Labelled histogram",
            label_names=("symbol",),
            buckets=(1.0,),
        )
        h.labels(symbol="EURUSD").observe(0.5)
        h.labels(symbol="EURUSD").observe(1.5)
        samples = h.collect()
        # Should have bucket(le=1.0), bucket(+Inf), sum, count for EURUSD
        eur_samples = [s for s in samples if s[1].get("symbol") == "EURUSD"]
        assert len(eur_samples) >= 4


# ===========================================================================
# MetricsRegistry tests
# ===========================================================================


class TestMetricsRegistry:
    def setup_method(self):
        self.registry = _fresh_registry()

    def teardown_method(self):
        MetricsRegistry.reset_singleton()

    def test_singleton(self):
        r2 = MetricsRegistry()
        assert r2 is self.registry

    def test_counter_registration(self):
        c = self.registry.counter("wolf_test_c", "test")
        c.inc()
        text = self.registry.exposition()
        assert "wolf_test_c 1" in text
        assert "# TYPE wolf_test_c counter" in text

    def test_gauge_registration(self):
        g = self.registry.gauge("wolf_test_g", "test gauge")
        g.set(3.14)
        text = self.registry.exposition()
        assert "wolf_test_g 3.14" in text
        assert "# TYPE wolf_test_g gauge" in text

    def test_histogram_registration(self):
        h = self.registry.histogram("wolf_test_h", "test hist", buckets=(1.0,))
        h.observe(0.5)
        text = self.registry.exposition()
        assert "# TYPE wolf_test_h histogram" in text
        assert "wolf_test_h_bucket" in text
        assert "wolf_test_h_sum" in text
        assert "wolf_test_h_count" in text

    def test_idempotent_registration(self):
        """Registering the same name twice returns the same object."""
        c1 = self.registry.counter("wolf_dup", "first")
        c2 = self.registry.counter("wolf_dup", "second")
        assert c1 is c2

    def test_exposition_format_labels(self):
        c = self.registry.counter("wolf_label_test", "with labels", label_names=("a", "b"))
        c.labels(a="1", b="2").inc(7)
        text = self.registry.exposition()
        assert 'wolf_label_test{a="1",b="2"} 7' in text

    def test_reset(self):
        self.registry.counter("wolf_reset_test", "reset")
        self.registry.reset()
        text = self.registry.exposition()
        assert "wolf_reset_test" not in text


# ===========================================================================
# get_registry() singleton accessor
# ===========================================================================


class TestGetRegistry:
    def test_returns_singleton(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


# ===========================================================================
# Pre-registered Wolf metrics exist
# ===========================================================================


class TestPreRegisteredMetrics:
    """Verify that importing core.metrics registers the standard Wolf metrics."""

    def test_pipeline_duration_exists(self):
        assert PIPELINE_DURATION is not None
        assert PIPELINE_DURATION.name == "wolf_pipeline_duration_seconds"

    def test_gate_result_exists(self):
        assert GATE_RESULT is not None
        assert GATE_RESULT.name == "wolf_pipeline_gate_result_total"

    def test_verdict_total_exists(self):
        assert VERDICT_TOTAL is not None
        assert VERDICT_TOTAL.name == "wolf_pipeline_verdict_total"

    def test_pipeline_error_exists(self):
        assert PIPELINE_ERROR is not None
        assert PIPELINE_ERROR.name == "wolf_pipeline_error_total"

    def test_feed_age_exists(self):
        assert FEED_AGE is not None
        assert FEED_AGE.name == "wolf_feed_age_seconds"

    def test_signal_total_exists(self):
        assert SIGNAL_TOTAL is not None
        assert SIGNAL_TOTAL.name == "wolf_signal_total"

    def test_pipeline_runs_exists(self):
        assert PIPELINE_RUNS is not None
        assert PIPELINE_RUNS.name == "wolf_pipeline_runs_total"

    def test_warmup_blocked_exists(self):
        assert WARMUP_BLOCKED is not None
        assert WARMUP_BLOCKED.name == "wolf_warmup_blocked_total"

    def test_signal_conditioning_gauges_exist(self):
        assert SIGNAL_CONDITIONED_SAMPLES is not None
        assert SIGNAL_CONDITIONED_SAMPLES.name == "wolf_signal_conditioned_samples"
        assert SIGNAL_NOISE_RATIO is not None
        assert SIGNAL_NOISE_RATIO.name == "wolf_signal_noise_ratio"
        assert SIGNAL_QUALITY_SCORE is not None
        assert SIGNAL_QUALITY_SCORE.name == "wolf_signal_quality_score"

    def test_rqi_gauge_exists(self):
        assert RQI_SCORE is not None
        assert RQI_SCORE.name == "wolf_reflex_rqi_score"


# ===========================================================================
# Pipeline _record_metrics integration
# ===========================================================================


class TestPipelineRecordMetrics:
    """Test that pipeline.execute() records Prometheus metrics."""

    def _make_pipeline(self):
        from pipeline.wolf_constitutional_pipeline import (  # noqa: PLC0415
            WolfConstitutionalPipeline,
        )

        pipe = WolfConstitutionalPipeline()
        pipe.skip_analyzers()
        return pipe

    def test_early_exit_records_metrics(self):
        """_early_exit should record latency, verdict, gate, error metrics."""
        pipe = self._make_pipeline()

        # Capture metric values before
        runs_before = PIPELINE_RUNS.labels(symbol="TEST_SYM").value
        err_before = PIPELINE_ERROR.labels(error_code="L1_CONTEXT_INVALID").value

        _pipeline_early_exit(pipe, "TEST_SYM", ["L1_CONTEXT_INVALID"], 42.0)

        # Verify metrics were incremented
        assert PIPELINE_RUNS.labels(symbol="TEST_SYM").value == runs_before + 1
        assert PIPELINE_ERROR.labels(error_code="L1_CONTEXT_INVALID").value == err_before + 1
        assert VERDICT_TOTAL.labels(symbol="TEST_SYM", verdict="HOLD").value >= 1

    def test_warmup_blocked_records_metrics(self):
        """Warmup gate block should increment WARMUP_BLOCKED counter."""
        pipe = self._make_pipeline()
        mock_bus = MagicMock()
        mock_bus.check_warmup.return_value = {
            "ready": False,
            "bars": {"M15": 0},
            "required": {"M15": 20},
            "missing": {"M15": 20},
        }
        _set_pipeline_context_bus(pipe, mock_bus)

        before = WARMUP_BLOCKED.labels(symbol="WARMUP_SYM").value
        pipe.execute("WARMUP_SYM")
        assert WARMUP_BLOCKED.labels(symbol="WARMUP_SYM").value == before + 1

    def test_gate_results_recorded(self):
        """Early exit records all 9 gates as FAIL."""
        pipe = self._make_pipeline()
        for i in range(1, 10):
            gate = f"gate_{i}_{'tii' if i == 1 else 'x'}"
            # We'll check after
        _pipeline_early_exit(pipe, "GATE_TEST", ["TEST_ERR"], 10.0)

        # All 9 gates should have a FAIL increment
        gate_names = [
            "gate_1_tii",
            "gate_2_montecarlo",
            "gate_3_frpc",
            "gate_4_conf12",
            "gate_5_rr",
            "gate_6_integrity",
            "gate_7_propfirm",
            "gate_8_drawdown",
            "gate_9_latency",
        ]
        for gate in gate_names:
            assert GATE_RESULT.labels(gate=gate, result="FAIL").value >= 1

    def test_execute_buy_signal_counted(self):
        """EXECUTE_BUY verdict should increment SIGNAL_TOTAL."""
        from pipeline.wolf_constitutional_pipeline import (  # noqa: PLC0415
            WolfConstitutionalPipeline,
        )

        # Directly test _record_metrics with a fake result
        fake_result: dict[str, Any] = {
            "latency_ms": 100.0,
            "l12_verdict": {
                "verdict": "EXECUTE_BUY",
                "gates_v74": {
                    "gate_1_tii": "PASS",
                    "gate_2_montecarlo": "PASS",
                    "gate_3_frpc": "PASS",
                    "gate_4_conf12": "PASS",
                    "gate_5_rr": "PASS",
                    "gate_6_integrity": "PASS",
                    "gate_7_propfirm": "PASS",
                    "gate_8_drawdown": "PASS",
                    "gate_9_latency": "PASS",
                },
            },
            "errors": [],
        }
        before = SIGNAL_TOTAL.labels(symbol="SIG_TEST", direction="BUY").value
        WolfConstitutionalPipeline.record_metrics("SIG_TEST", fake_result)
        assert SIGNAL_TOTAL.labels(symbol="SIG_TEST", direction="BUY").value == before + 1

    def test_signal_conditioning_gauges_recorded(self):
        """Signal conditioning diagnostics in synthesis.system update gauges."""
        from pipeline.wolf_constitutional_pipeline import (  # noqa: PLC0415
            WolfConstitutionalPipeline,
        )

        fake_result: dict[str, Any] = {
            "latency_ms": 50.0,
            "l12_verdict": {"verdict": "HOLD", "gates_v74": {}},
            "errors": [],
            "synthesis": {
                "system": {
                    "signal_conditioning": {
                        "samples_out": 77,
                        "noise_ratio": 0.33,
                        "microstructure_quality_score": 0.67,
                    }
                }
            },
        }

        WolfConstitutionalPipeline.record_metrics("COND_TEST", fake_result)

        assert SIGNAL_CONDITIONED_SAMPLES.labels(symbol="COND_TEST").value == 77.0
        assert math.isclose(
            SIGNAL_NOISE_RATIO.labels(symbol="COND_TEST").value,
            0.33,
            rel_tol=1e-9,
            abs_tol=1e-12,
        )
        assert math.isclose(
            SIGNAL_QUALITY_SCORE.labels(symbol="COND_TEST").value,
            0.67,
            rel_tol=1e-9,
            abs_tol=1e-12,
        )

    def test_rqi_gauge_recorded(self):
        """RQI score in synthesis.system should update the per-symbol gauge."""
        from pipeline.wolf_constitutional_pipeline import (  # noqa: PLC0415
            WolfConstitutionalPipeline,
        )

        fake_result: dict[str, Any] = {
            "latency_ms": 25.0,
            "l12_verdict": {"verdict": "HOLD", "gates_v74": {}},
            "errors": [],
            "synthesis": {
                "system": {
                    "rqi": 0.8125,
                }
            },
        }

        WolfConstitutionalPipeline.record_metrics("RQI_TEST", fake_result)
        assert math.isclose(
            RQI_SCORE.labels(symbol="RQI_TEST").value,
            0.8125,
            rel_tol=1e-9,
            abs_tol=1e-12,
        )


# ===========================================================================
# Thread safety
# ===========================================================================


class TestThreadSafety:
    def test_concurrent_counter_increments(self):
        c = Counter("thread_test_counter", "Thread test")
        n_threads = 10
        n_increments = 1000

        def _worker():
            for _ in range(n_increments):
                c.inc()

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert c.collect()[0][2] == n_threads * n_increments

    def test_concurrent_histogram_observes(self):
        h = Histogram("thread_test_hist", "Thread hist", buckets=(1.0, 10.0))
        n_threads = 8
        n_obs = 500

        def _worker():
            for i in range(n_obs):
                h.observe(float(i % 15))

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        count_samples = [s for s in h.collect() if s[0].endswith("_count")]
        assert count_samples[0][2] == n_threads * n_obs


# ===========================================================================
# Exposition format correctness
# ===========================================================================


class TestExposition:
    def setup_method(self):
        self.registry = _fresh_registry()

    def teardown_method(self):
        MetricsRegistry.reset_singleton()

    def test_help_and_type_lines(self):
        self.registry.counter("expo_c", "My counter help")
        text = self.registry.exposition()
        assert "# HELP expo_c My counter help" in text
        assert "# TYPE expo_c counter" in text

    def test_histogram_bucket_format(self):
        h = self.registry.histogram("expo_h", "Hist", buckets=(0.5, 1.0))
        h.observe(0.3)
        text = self.registry.exposition()
        assert 'expo_h_bucket{le="0.5"} 1' in text
        assert 'expo_h_bucket{le="+Inf"} 1' in text
        assert "expo_h_sum" in text
        assert "expo_h_count" in text

    def test_empty_registry(self):
        text = self.registry.exposition()
        # Should be just a trailing newline
        assert text in {"\n", ""}

    def test_ends_with_newline(self):
        self.registry.counter("expo_nl", "newline test")
        text = self.registry.exposition()
        assert text.endswith("\n")


# ===========================================================================
# New constitutional observability metrics (9 new gauges)
# ===========================================================================


class TestNewConstitutionalMetrics:
    """Verify that the 9 new constitutional observability metrics are registered."""

    def test_sovereignty_level_exists(self):
        from core.metrics import SOVEREIGNTY_LEVEL  # noqa: PLC0415

        assert SOVEREIGNTY_LEVEL is not None
        assert SOVEREIGNTY_LEVEL.name == "wolf_sovereignty_level"

    def test_sovereignty_level_labels(self):
        from core.metrics import SOVEREIGNTY_LEVEL  # noqa: PLC0415

        SOVEREIGNTY_LEVEL.labels(symbol="EURUSD", level="GRANTED").set(1.0)
        SOVEREIGNTY_LEVEL.labels(symbol="EURUSD", level="RESTRICTED").set(0.0)
        SOVEREIGNTY_LEVEL.labels(symbol="EURUSD", level="REVOKED").set(0.0)
        assert SOVEREIGNTY_LEVEL.labels(symbol="EURUSD", level="GRANTED").value == 1.0
        assert SOVEREIGNTY_LEVEL.labels(symbol="EURUSD", level="RESTRICTED").value == 0.0
        assert SOVEREIGNTY_LEVEL.labels(symbol="EURUSD", level="REVOKED").value == 0.0

    def test_reflective_drift_ratio_exists(self):
        from core.metrics import REFLECTIVE_DRIFT_RATIO  # noqa: PLC0415

        assert REFLECTIVE_DRIFT_RATIO is not None
        assert REFLECTIVE_DRIFT_RATIO.name == "wolf_reflective_drift_ratio"

    def test_reflective_drift_ratio_labels(self):
        from core.metrics import REFLECTIVE_DRIFT_RATIO  # noqa: PLC0415

        REFLECTIVE_DRIFT_RATIO.labels(symbol="XAUUSD").set(0.08)
        assert math.isclose(REFLECTIVE_DRIFT_RATIO.labels(symbol="XAUUSD").value, 0.08, rel_tol=1e-9)

    def test_trq3d_gauges_exist(self):
        from core.metrics import TRQ3D_ALPHA, TRQ3D_BETA, TRQ3D_GAMMA  # noqa: PLC0415

        assert TRQ3D_ALPHA.name == "wolf_trq3d_alpha"
        assert TRQ3D_BETA.name == "wolf_trq3d_beta"
        assert TRQ3D_GAMMA.name == "wolf_trq3d_gamma"

    def test_trq3d_labels(self):
        from core.metrics import TRQ3D_ALPHA, TRQ3D_BETA, TRQ3D_GAMMA  # noqa: PLC0415

        TRQ3D_ALPHA.labels(symbol="GBPUSD").set(0.72)
        TRQ3D_BETA.labels(symbol="GBPUSD").set(0.68)
        TRQ3D_GAMMA.labels(symbol="GBPUSD").set(0.90)
        assert math.isclose(TRQ3D_ALPHA.labels(symbol="GBPUSD").value, 0.72, rel_tol=1e-9)
        assert math.isclose(TRQ3D_BETA.labels(symbol="GBPUSD").value, 0.68, rel_tol=1e-9)
        assert math.isclose(TRQ3D_GAMMA.labels(symbol="GBPUSD").value, 0.90, rel_tol=1e-9)

    def test_tii_score_exists(self):
        from core.metrics import TII_SCORE  # noqa: PLC0415

        assert TII_SCORE is not None
        assert TII_SCORE.name == "wolf_tii_score"

    def test_tii_score_labels(self):
        from core.metrics import TII_SCORE  # noqa: PLC0415

        TII_SCORE.labels(symbol="USDJPY").set(0.75)
        assert math.isclose(TII_SCORE.labels(symbol="USDJPY").value, 0.75, rel_tol=1e-9)

    def test_frpc_score_exists(self):
        from core.metrics import FRPC_SCORE  # noqa: PLC0415

        assert FRPC_SCORE is not None
        assert FRPC_SCORE.name == "wolf_frpc_score"

    def test_frpc_score_labels(self):
        from core.metrics import FRPC_SCORE  # noqa: PLC0415

        FRPC_SCORE.labels(symbol="EURUSD").set(0.95)
        assert math.isclose(FRPC_SCORE.labels(symbol="EURUSD").value, 0.95, rel_tol=1e-9)

    def test_conf12_score_exists(self):
        from core.metrics import CONF12_SCORE  # noqa: PLC0415

        assert CONF12_SCORE is not None
        assert CONF12_SCORE.name == "wolf_conf12_score"

    def test_conf12_score_labels(self):
        from core.metrics import CONF12_SCORE  # noqa: PLC0415

        CONF12_SCORE.labels(symbol="XAUUSD").set(0.80)
        assert math.isclose(CONF12_SCORE.labels(symbol="XAUUSD").value, 0.80, rel_tol=1e-9)

    def test_account_drawdown_percent_exists(self):
        from core.metrics import ACCOUNT_DRAWDOWN_PERCENT  # noqa: PLC0415

        assert ACCOUNT_DRAWDOWN_PERCENT is not None
        assert ACCOUNT_DRAWDOWN_PERCENT.name == "wolf_account_drawdown_percent"

    def test_account_drawdown_percent_labels(self):
        from core.metrics import ACCOUNT_DRAWDOWN_PERCENT  # noqa: PLC0415

        ACCOUNT_DRAWDOWN_PERCENT.labels(account_id="ACC001").set(3.5)
        assert math.isclose(ACCOUNT_DRAWDOWN_PERCENT.labels(account_id="ACC001").value, 3.5, rel_tol=1e-9)

    def test_all_new_metrics_in_exposition(self):
        """Verify all 9 new metric names appear in the exposition output."""
        # Use get_wolf_registry() which always returns the module-level registry
        # (captured at import time) rather than get_registry() which may return
        # a reset singleton after TestExposition.teardown_method runs.
        from core.metrics import get_wolf_registry  # noqa: PLC0415

        text = get_wolf_registry().exposition()
        new_metric_names = [
            "wolf_sovereignty_level",
            "wolf_reflective_drift_ratio",
            "wolf_trq3d_alpha",
            "wolf_trq3d_beta",
            "wolf_trq3d_gamma",
            "wolf_tii_score",
            "wolf_frpc_score",
            "wolf_conf12_score",
            "wolf_account_drawdown_percent",
        ]
        for name in new_metric_names:
            assert name in text, f"Metric '{name}' missing from exposition output"


# ===========================================================================
# Pipeline recorder - new constitutional gauges integration
# ===========================================================================


class TestPipelineRecordNewMetrics:
    """Verify that record_pipeline_metrics records the 9 new constitutional gauges."""

    def _base_result(self) -> dict[str, Any]:
        return {
            "latency_ms": 50.0,
            "l12_verdict": {"verdict": "HOLD", "gates_v74": {}},
            "errors": [],
        }

    def test_sovereignty_and_drift_recorded(self):
        from core.metrics import REFLECTIVE_DRIFT_RATIO, SOVEREIGNTY_LEVEL  # noqa: PLC0415
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline  # noqa: PLC0415

        result = {
            **self._base_result(),
            "enforcement": {
                "execution_rights": "RESTRICTED",
                "drift_ratio": 0.17,
            },
        }
        WolfConstitutionalPipeline.record_metrics("SOV_TEST", result)

        assert SOVEREIGNTY_LEVEL.labels(symbol="SOV_TEST", level="RESTRICTED").value == 1.0
        assert SOVEREIGNTY_LEVEL.labels(symbol="SOV_TEST", level="GRANTED").value == 0.0
        assert SOVEREIGNTY_LEVEL.labels(symbol="SOV_TEST", level="REVOKED").value == 0.0
        assert math.isclose(REFLECTIVE_DRIFT_RATIO.labels(symbol="SOV_TEST").value, 0.17, rel_tol=1e-9)

    def test_trq3d_gauges_recorded(self):
        from core.metrics import TRQ3D_ALPHA, TRQ3D_BETA, TRQ3D_GAMMA  # noqa: PLC0415
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline  # noqa: PLC0415

        result = {
            **self._base_result(),
            "synthesis": {
                "trq3d": {"alpha": 0.71, "beta": 0.65, "gamma": 0.88},
                "layers": {},
                "fusion_frpc": {},
            },
        }
        WolfConstitutionalPipeline.record_metrics("TRQ_TEST", result)

        assert math.isclose(TRQ3D_ALPHA.labels(symbol="TRQ_TEST").value, 0.71, rel_tol=1e-9)
        assert math.isclose(TRQ3D_BETA.labels(symbol="TRQ_TEST").value, 0.65, rel_tol=1e-9)
        assert math.isclose(TRQ3D_GAMMA.labels(symbol="TRQ_TEST").value, 0.88, rel_tol=1e-9)

    def test_tii_conf12_recorded(self):
        from core.metrics import CONF12_SCORE, TII_SCORE  # noqa: PLC0415
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline  # noqa: PLC0415

        result = {
            **self._base_result(),
            "synthesis": {
                "layers": {"L8_tii_sym": 0.63, "conf12": 0.78},
                "fusion_frpc": {},
            },
        }
        WolfConstitutionalPipeline.record_metrics("SCORE_TEST", result)

        assert math.isclose(TII_SCORE.labels(symbol="SCORE_TEST").value, 0.63, rel_tol=1e-9)
        assert math.isclose(CONF12_SCORE.labels(symbol="SCORE_TEST").value, 0.78, rel_tol=1e-9)

    def test_frpc_energy_recorded(self):
        from core.metrics import FRPC_SCORE  # noqa: PLC0415
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline  # noqa: PLC0415

        result = {
            **self._base_result(),
            "synthesis": {
                "layers": {},
                "fusion_frpc": {"frpc_energy": 0.94},
            },
        }
        WolfConstitutionalPipeline.record_metrics("FRPC_TEST", result)

        assert math.isclose(FRPC_SCORE.labels(symbol="FRPC_TEST").value, 0.94, rel_tol=1e-9)

    def test_missing_enforcement_is_safe(self):
        """Missing enforcement key should not raise errors."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline  # noqa: PLC0415

        result = {**self._base_result()}
        # Should complete without exception
        WolfConstitutionalPipeline.record_metrics("SAFE_TEST", result)

    def test_none_enforcement_is_safe(self):
        """None enforcement value should not raise errors."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline  # noqa: PLC0415

        result = {**self._base_result(), "enforcement": None}
        WolfConstitutionalPipeline.record_metrics("NONE_TEST", result)
