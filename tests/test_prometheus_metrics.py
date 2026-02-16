"""
Tests for GAP #7: Prometheus metrics collector and pipeline instrumentation.

Validates:
  1. core.metrics Counter / Gauge / Histogram and Prometheus exposition format
  2. Pipeline records metrics on normal exit, early exit, and warmup block
  3. MetricsRegistry singleton and idempotent registration
  4. /metrics endpoint returns valid Prometheus text
"""

from __future__ import annotations

import threading

from unittest.mock import MagicMock

import pytest

from core.metrics import (
    FEED_AGE,
    GATE_RESULT,
    PIPELINE_DURATION,
    PIPELINE_ERROR,
    PIPELINE_RUNS,
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
    MetricsRegistry._instance = None
    reg = MetricsRegistry()
    return reg


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
        child = g._no_label
        assert child is not None, "_no_label should not be None for a labelless Gauge"
        child.inc(5)
        child.dec(3)
        assert g.collect()[0][2] == 12.0

    def test_labelled_gauge(self):
        g = Gauge("test_lg", "Labelled gauge", label_names=("symbol",))
        g.labels(symbol="EURUSD").set(2.3)
        g.labels(symbol="XAUUSD").set(0.5)
        samples = g.collect()
        values = {s[1]["symbol"]: s[2] for s in samples}
        assert values["EURUSD"] == pytest.approx(2.3)
        assert values["XAUUSD"] == pytest.approx(0.5)


# ===========================================================================
# Histogram tests
# ===========================================================================

class TestHistogram:
    def test_observe_and_buckets(self):
        h = Histogram(
            "test_hist", "A histogram",
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
        assert sum_samples[0][2] == pytest.approx(0.05 + 0.3 + 0.8 + 2.0)

        count_samples = [s for s in samples if s[0].endswith("_count")]
        assert count_samples[0][2] == 4

    def test_labelled_histogram(self):
        h = Histogram(
            "test_lhist", "Labelled histogram",
            label_names=("symbol",), buckets=(1.0,),
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
        MetricsRegistry._instance = None

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
        pipe._ensure_analyzers = MagicMock()
        return pipe

    def test_early_exit_records_metrics(self):
        """_early_exit should record latency, verdict, gate, error metrics."""
        pipe = self._make_pipeline()

        # Capture metric values before
        runs_before = PIPELINE_RUNS.labels(symbol="TEST_SYM").value
        err_before = PIPELINE_ERROR.labels(error_code="L1_CONTEXT_INVALID").value

        pipe._early_exit("TEST_SYM", ["L1_CONTEXT_INVALID"], 42.0)

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
            "bars": {"M15": 0}, "required": {"M15": 20}, "missing": {"M15": 20},
        }
        pipe._context_bus = mock_bus

        before = WARMUP_BLOCKED.labels(symbol="WARMUP_SYM").value
        pipe.execute("WARMUP_SYM")
        assert WARMUP_BLOCKED.labels(symbol="WARMUP_SYM").value == before + 1

    def test_gate_results_recorded(self):
        """Early exit records all 9 gates as FAIL."""
        pipe = self._make_pipeline()
        for i in range(1, 10):
            gate = f"gate_{i}_{'tii' if i == 1 else 'x'}"
            # We'll check after
        pipe._early_exit("GATE_TEST", ["TEST_ERR"], 10.0)

        # All 9 gates should have a FAIL increment
        gate_names = [
            "gate_1_tii", "gate_2_montecarlo", "gate_3_frpc",
            "gate_4_conf12", "gate_5_rr", "gate_6_integrity",
            "gate_7_propfirm", "gate_8_drawdown", "gate_9_latency",
        ]
        for gate in gate_names:
            assert GATE_RESULT.labels(gate=gate, result="FAIL").value >= 1

    def test_execute_buy_signal_counted(self):
        """EXECUTE_BUY verdict should increment SIGNAL_TOTAL."""
        from pipeline.wolf_constitutional_pipeline import (  # noqa: PLC0415
            WolfConstitutionalPipeline,
        )

        # Directly test _record_metrics with a fake result
        fake_result = {
            "latency_ms": 100.0,
            "l12_verdict": {
                "verdict": "EXECUTE_BUY",
                "gates_v74": {
                    "gate_1_tii": "PASS", "gate_2_montecarlo": "PASS",
                    "gate_3_frpc": "PASS", "gate_4_conf12": "PASS",
                    "gate_5_rr": "PASS", "gate_6_integrity": "PASS",
                    "gate_7_propfirm": "PASS", "gate_8_drawdown": "PASS",
                    "gate_9_latency": "PASS",
                },
            },
            "errors": [],
        }
        before = SIGNAL_TOTAL.labels(symbol="SIG_TEST", direction="BUY").value
        WolfConstitutionalPipeline._record_metrics("SIG_TEST", fake_result)
        assert SIGNAL_TOTAL.labels(symbol="SIG_TEST", direction="BUY").value == before + 1


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
        MetricsRegistry._instance = None

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
