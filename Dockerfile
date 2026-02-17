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

# Configurable workers via WEB_CONCURRENCY (default 2)
ENV WEB_CONCURRENCY=2

# --- Healthcheck (uses $PORT so it follows the actual listening port) ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Gunicorn writes startup/app logs to stderr by default (--error-logfile -).
# Container platforms (Railway, Render, GCP, etc.) classify stderr as "error",
# so we redirect stderr → stdout (2>&1) to keep everything on fd 1.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY} --timeout 120 --access-logfile - --error-logfile - --log-level info dashboard.app:app 2>&1"]
