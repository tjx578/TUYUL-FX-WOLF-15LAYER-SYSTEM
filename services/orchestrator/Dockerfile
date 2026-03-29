# ──────────────────────────────────────────────────────────────────────
# Orchestrator Dockerfile — scoped to orchestrator-relevant packages.
#
# Build from repository ROOT:
#   docker build -f services/orchestrator/Dockerfile .
# ──────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Scoped COPY: orchestrator + shared packages ───────────────────────
COPY config/ config/
COPY context/ context/
COPY contracts/ contracts/
COPY core/ core/
COPY execution/ execution/
COPY infrastructure/ infrastructure/
COPY monitoring/ monitoring/
COPY risk/ risk/
COPY schemas/ schemas/
COPY state/ state/
COPY storage/ storage/
COPY utils/ utils/
COPY services/orchestrator/ services/orchestrator/

# Root modules
COPY config_loader.py throttle_log_filter.py ./

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE ${ORCHESTRATOR_HEALTH_PORT:-8083}

HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${ORCHESTRATOR_HEALTH_PORT:-8083}/healthz || exit 1

CMD ["python", "-m", "services.orchestrator.state_manager"]
