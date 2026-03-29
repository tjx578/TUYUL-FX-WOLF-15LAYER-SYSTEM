# ──────────────────────────────────────────────────────────────────────
# Engine Dockerfile — scoped to engine-relevant packages.
#
# Build from repository ROOT:
#   docker build -f services/engine/Dockerfile .
#
# Migrations are NOT run here.  Use the dedicated wolf15-migrator service
# (railway-migrator.toml / deploy/railway/start_migrator.sh) to avoid
# race conditions when multiple services deploy simultaneously.
# ──────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Scoped COPY: engine + all shared packages ─────────────────────────
COPY accounts/ accounts/
COPY agents/ agents/
COPY alerts/ alerts/
COPY allocation/ allocation/
COPY analysis/ analysis/
COPY api/ api/
COPY config/ config/
COPY context/ context/
COPY contracts/ contracts/
COPY core/ core/
COPY dashboard/ dashboard/
COPY ea_interface/ ea_interface/
COPY engines/ engines/
COPY execution/ execution/
COPY ingest/ ingest/
COPY infrastructure/ infrastructure/
COPY journal/ journal/
COPY monitoring/ monitoring/
COPY news/ news/
COPY pipeline/ pipeline/
COPY propfirm_manager/ propfirm_manager/
COPY risk/ risk/
COPY schemas/ schemas/
COPY startup/ startup/
COPY state/ state/
COPY storage/ storage/
COPY trq/ trq/
COPY utils/ utils/
COPY services/engine/ services/engine/
COPY services/orchestrator/ services/orchestrator/

# Root modules
COPY config_loader.py throttle_log_filter.py main.py ./

# Alembic (health-check queries; migrations run by migrator service)
COPY alembic.ini ./
COPY migrations/ migrations/

# Deploy utilities
COPY deploy/ deploy/

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE ${ENGINE_HEALTH_PORT:-8081}

HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${ENGINE_HEALTH_PORT:-8081}/healthz || exit 1

CMD ["python", "-m", "services.engine.runner"]
