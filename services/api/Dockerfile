# ──────────────────────────────────────────────────────────────────────
# TUYUL FX Server v7 — Production Dockerfile
# ──────────────────────────────────────────────────────────────────────
# Railway Config Required:
#   Root Directory  : /  (repo root, NOT services/api)
#   Dockerfile Path : services/api/Dockerfile
#   — OR move this Dockerfile to repo root
#
# Build from repository ROOT:
#   docker build -f services/api/Dockerfile .
# ──────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels

# ── Runtime stage ────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/* \
    && rm -rf /tmp/wheels

COPY . .

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["sh", "-c", "uvicorn services.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
