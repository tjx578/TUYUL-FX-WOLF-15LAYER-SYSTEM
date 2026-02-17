# Wolf 15-Layer Trading System - Dockerfile (Multi-stage build)

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

# --- Final stage ---
# Create non-root user
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

# Ensure app files are owned by appuser
RUN chown -R appuser:appgroup /app

USER appuser

# Configurable port
ENV PORT=8000
EXPOSE ${PORT}

# Configurable workers via WEB_CONCURRENCY (default 2)
ENV WEB_CONCURRENCY=2

# --- Healthcheck ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY} --timeout 120 dashboard.app:app"]
