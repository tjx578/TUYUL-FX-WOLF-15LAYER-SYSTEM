# ──────────────────────────────────────────────────────────────────────
# Ingest Dockerfile — scoped to ingest-relevant packages.
#
# Build from repository ROOT:
#   docker build -f services/ingest/Dockerfile .
# ──────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Scoped COPY: ingest + shared packages ────────────────────────────
COPY config/ config/
COPY context/ context/
COPY core/ core/
COPY ingest/ ingest/
COPY infrastructure/ infrastructure/
COPY monitoring/ monitoring/
COPY schemas/ schemas/
COPY storage/ storage/
COPY utils/ utils/
COPY services/ingest/ services/ingest/

# Root modules
COPY config_loader.py throttle_log_filter.py ./

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE ${INGEST_HEALTH_PORT:-8082}

HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${INGEST_HEALTH_PORT:-8082}/healthz || exit 1

CMD ["python", "-m", "services.ingest.ingest_worker"]
