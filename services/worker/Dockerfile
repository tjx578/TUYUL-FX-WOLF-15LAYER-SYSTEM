# ──────────────────────────────────────────────────────────────────────
# Worker Dockerfile — scoped to worker-relevant packages.
#
# Build from repository ROOT:
#   docker build -f services/worker/Dockerfile .
# ──────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Scoped COPY: worker + shared packages ────────────────────────────
COPY analysis/ analysis/
COPY config/ config/
COPY context/ context/
COPY core/ core/
COPY engines/ engines/
COPY infrastructure/ infrastructure/
COPY monitoring/ monitoring/
COPY schemas/ schemas/
COPY storage/ storage/
COPY utils/ utils/
COPY services/worker/ services/worker/

# Root modules
COPY config_loader.py throttle_log_filter.py ./

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "-m", "services.worker.montecarlo_job"]
