# Wolf 15-Layer Trading System - Dockerfile

FROM python:3.11-slim

LABEL maintainer="TUYUL-FX Wolf-15 Layer System"

# --- Security: create non-root user ---
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Install system deps (if any) then clean up
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# --- Security: switch to non-root user ---
RUN chown -R appuser:appuser /app
USER appuser

# Configurable port (platforms like Railway/Render override PORT)
ENV PORT=8000
EXPOSE ${PORT}

# Configurable workers via WEB_CONCURRENCY (default 1 for WebSocket support)
# NOTE: WebSocket connections are per-worker. With multiple workers,
# each WS client connects to ONE worker only. For real-time feeds,
# 1 worker is safest unless using Redis pub/sub for cross-worker broadcast.
ENV WEB_CONCURRENCY=1

# --- Healthcheck (uses $PORT so it follows the actual listening port) ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# CRITICAL FIXES:
# 1. Use api_server:app (NOT dashboard.app:app) — contains ALL routes + lifespan
# 2. Use uvicorn.workers.UvicornWorker (NOT sync) — required for WebSocket/ASGI
# 3. WEB_CONCURRENCY=1 default for WS state consistency
#
# Route Gunicorn access + error logs to stdout to avoid false `severity:error`
# classifications on platforms that treat stderr as operational errors.
# Gunicorn emits INFO lifecycle logs via the error logger.
# Many container log collectors classify stderr as severity=error, so route
# Gunicorn's error logger to stdout to avoid false-positive "error" events.
CMD ["sh", "-c", "exec gunicorn api_server:app --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY} --worker-class uvicorn.workers.UvicornWorker --timeout 120 --access-logfile - --error-logfile /dev/stdout --log-level info"]
