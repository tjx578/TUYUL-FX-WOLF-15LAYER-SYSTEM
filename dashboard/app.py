from fastapi import FastAPI, Response

from dashboard.metrics import get_metrics_bytes

app = FastAPI()

# ── Prometheus /metrics endpoint ─────────────────────────────────────

@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Expose Prometheus-compatible metrics for external scraping.

    Zone: dashboard (observability). No execution authority.
    """
    body, content_type = get_metrics_bytes()
    return Response(content=body, media_type=content_type)
