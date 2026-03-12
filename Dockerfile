# ==========================================================================
# TUYUL FX Wolf-15 — Multi-stage production Dockerfile
# ==========================================================================
# Stage 1: build wheels (with build tools, discarded at runtime)
# Stage 2: lean runtime image (~150 MB smaller than single-stage)
# ==========================================================================

# ---------- STAGE 1: BUILD ----------
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels

# ---------- STAGE 2: RUNTIME ----------
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENV=production \
    PORT=8000

# Postgres client lib required by psycopg / alembic at runtime
# curl required for HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Install wheels from builder (no compiler needed)
COPY --from=builder /wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/* \
    && rm -rf /tmp/wheels

# Copy application code (filtered by .dockerignore)
COPY . .

# Non-root user
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD ["python", "api_server.py"]
