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
    && apt-get install -y --no-install-recommends build-essential gcc \
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
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install wheels from builder (no compiler needed)
COPY --from=builder /wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/* \
    && rm -rf /tmp/wheels

# Copy only application code (respect .dockerignore)
COPY api/ api/
COPY accounts/ accounts/
COPY alerts/ alerts/
COPY allocation/ allocation/
COPY analysis/ analysis/
COPY config/ config/
COPY constitution/ constitution/
COPY context/ context/
COPY contracts/ contracts/
COPY core/ core/
COPY dashboard/ dashboard/
COPY deploy/ deploy/
COPY ea_interface/ ea_interface/
COPY engines/ engines/
COPY execution/ execution/
COPY infrastructure/ infrastructure/
COPY ingest/ ingest/
COPY journal/ journal/
COPY monitoring/ monitoring/
COPY news/ news/
COPY ops/ ops/
COPY pipeline/ pipeline/
COPY propfirm_manager/ propfirm_manager/
COPY risk/ risk/
COPY schemas/ schemas/
COPY services/ services/
COPY state/ state/
COPY storage/ storage/
COPY utils/ utils/

# Copy top-level entry points & config
COPY api_server.py app.py config_loader.py main.py ingest_service.py alembic.ini ./

# Non-root user
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, sys, urllib.request; url = os.getenv('CONTAINER_HEALTHCHECK_URL', '').strip();\
sys.exit(0 if not url else (0 if urllib.request.urlopen(url, timeout=5).status < 500 else 1))" || exit 1

CMD ["python", "api_server.py"]
