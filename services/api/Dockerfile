# ──────────────────────────────────────────────────────────────────────
# API-only Dockerfile — scoped to API-relevant packages.
#
# Build from repository ROOT:
#   docker build -f services/api/Dockerfile .
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

# ── Scoped COPY: only API-relevant packages ──────────────────────────
# Core application packages
COPY api/ api/
COPY accounts/ accounts/
COPY agents/ agents/
COPY allocation/ allocation/
COPY config/ config/
COPY context/ context/
COPY contracts/ contracts/
COPY core/ core/
COPY execution/ execution/
COPY infrastructure/ infrastructure/
COPY journal/ journal/
COPY monitoring/ monitoring/
COPY news/ news/
COPY pipeline/ pipeline/
COPY propfirm_manager/ propfirm_manager/
COPY risk/ risk/
COPY schemas/ schemas/
COPY state/ state/
COPY storage/ storage/
COPY utils/ utils/
COPY services/api/ services/api/
COPY services/orchestrator/ services/orchestrator/

# Root modules required by API
COPY config_loader.py throttle_log_filter.py ./

# Deploy utilities
COPY deploy/ deploy/

# Alembic (migration infra — supports on-demand `alembic current` /
# health-check queries but NOT auto-run on boot; see migrator service)
COPY alembic.ini ./
COPY migrations/ migrations/

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE ${PORT:-8000}

HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${PORT:-8000}/healthz || exit 1

# Use the self-contained service entrypoint — no root api_server.py dependency.
CMD ["gunicorn", "services.api.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000"]
