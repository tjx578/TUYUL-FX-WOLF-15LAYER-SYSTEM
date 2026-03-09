"""
Tests for the Prometheus metrics endpoint and HTTP instrumentation middleware.

Covers:
  1. GET /metrics returns 200 with correct Content-Type
  2. Response body is valid Prometheus text exposition format
  3. Pre-registered Wolf metrics appear in the output
  4. PrometheusMiddleware increments counters and observes histograms
  5. /metrics path itself is excluded from instrumentation (no feedback loop)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.metrics_routes import router as metrics_router
from api.middleware.prometheus_middleware import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
    PrometheusMiddleware,
)
from core.metrics import PIPELINE_RUNS, VERDICT_TOTAL, get_registry
from monitoring.pipeline_metrics import record_pipeline_latency

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    """Return a minimal FastAPI app with the metrics router and middleware."""
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)
    app.include_router(metrics_router)

    @app.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    return app


# ===========================================================================
# Metrics endpoint
# ===========================================================================


class TestMetricsEndpoint:
    """GET /metrics returns valid Prometheus text exposition."""

    @pytest.fixture(autouse=True)
    def client(self):
        self._client = TestClient(_make_app())
        yield
        self._client.close()

    def test_status_200(self):
        r = self._client.get("/metrics")
        assert r.status_code == 200

    def test_content_type(self):
        r = self._client.get("/metrics")
        assert "text/plain" in r.headers["content-type"]
        assert "0.0.4" in r.headers["content-type"]

    def test_help_and_type_lines_present(self):
        """At minimum the pre-registered Wolf metrics should appear."""
        r = self._client.get("/metrics")
        body = r.text
        assert "# HELP wolf_pipeline_runs_total" in body
        assert "# TYPE wolf_pipeline_runs_total counter" in body
        assert "# HELP wolf_pipeline_verdict_total" in body

    def test_response_ends_with_newline(self):
        r = self._client.get("/metrics")
        assert r.text.endswith("\n")

    def test_incremented_counter_appears(self):
        """Values written to the registry show up in /metrics output."""
        PIPELINE_RUNS.labels(symbol="METRICS_TEST").inc(3)
        r = self._client.get("/metrics")
        body = r.text
        assert "METRICS_TEST" in body

    def test_verdict_total_label_format(self):
        """Label format matches Prometheus convention."""
        VERDICT_TOTAL.labels(symbol="FMT_TEST", verdict="HOLD").inc()
        r = self._client.get("/metrics")
        body = r.text
        assert 'symbol="FMT_TEST"' in body


# ===========================================================================
# HTTP instrumentation middleware
# ===========================================================================


class TestPrometheusMiddleware:
    """PrometheusMiddleware records request counts and latencies."""

    @pytest.fixture(autouse=True)
    def client(self):
        self._app = _make_app()
        self._client = TestClient(self._app)
        yield
        self._client.close()

    def test_request_counter_increments(self):
        before = HTTP_REQUESTS_TOTAL.labels(
            method="GET", path_template="/api/v1/ping", status_code="200"
        ).value
        self._client.get("/api/v1/ping")
        after = HTTP_REQUESTS_TOTAL.labels(
            method="GET", path_template="/api/v1/ping", status_code="200"
        ).value
        assert after == before + 1

    def test_duration_histogram_records(self):
        before_count = HTTP_REQUEST_DURATION.labels(
            method="GET", path_template="/api/v1/ping"
        ).count
        self._client.get("/api/v1/ping")
        after_count = HTTP_REQUEST_DURATION.labels(
            method="GET", path_template="/api/v1/ping"
        ).count
        assert after_count == before_count + 1

    def test_metrics_path_not_instrumented(self):
        """Scraping /metrics should not add an entry for /metrics itself."""
        before = HTTP_REQUESTS_TOTAL.labels(
            method="GET", path_template="/metrics", status_code="200"
        ).value
        self._client.get("/metrics")
        after = HTTP_REQUESTS_TOTAL.labels(
            method="GET", path_template="/metrics", status_code="200"
        ).value
        assert after == before, "/metrics must not be instrumented (cardinality guard)"

    def test_counter_shows_in_metrics_output(self):
        """End-to-end: hit /api/v1/ping, then verify counter appears in /metrics."""
        self._client.get("/api/v1/ping")
        r = self._client.get("/metrics")
        assert "wolf_http_requests_total" in r.text
        assert "wolf_http_request_duration_seconds" in r.text


# ===========================================================================
# Registry content validation
# ===========================================================================


class TestRegistryContent:
    """Standard Wolf metrics are always present."""

    def test_wolf_metrics_registered(self):
        reg = get_registry()
        names = {m.name for m in reg._metrics}  # noqa: SLF001
        expected = {
            "wolf_pipeline_runs_total",
            "wolf_pipeline_verdict_total",
            "wolf_pipeline_duration_seconds",
            "wolf_pipeline_gate_result_total",
            "wolf_feed_age_seconds",
            "wolf_signal_total",
            "wolf_warmup_blocked_total",
            "wolf_pipeline_latency_ms",
            "wolf_active_pairs",
            "wolf_system_healthy",
        }
        assert expected.issubset(names), f"Missing metrics: {expected - names}"


class TestSLOEndpoint:
    @pytest.fixture(autouse=True)
    def client(self):
        self._client = TestClient(_make_app())
        yield
        self._client.close()

    def test_metrics_slo_endpoint_returns_shape(self):
        response = self._client.get("/metrics/slo")
        assert response.status_code == 200
        payload = response.json()
        assert "slo" in payload
        assert "alerts" in payload

    def test_metrics_slo_alerts_when_threshold_breached(self):
        stage = "chaos_slo_stage"
        for _ in range(8):
            record_pipeline_latency(stage=stage, latency_ms=450.0)

        response = self._client.get(
            "/metrics/slo",
            params={"latency_threshold_ms": 100.0, "min_samples": 5},
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["slo"]["healthy"] is False
        assert any(alert["event"] == "SLO_THRESHOLD_BREACH" for alert in payload["alerts"])
        assert any(
            row["stage"] == stage and row["breach"] is True
            for row in payload["slo"]["stages"]
        )
