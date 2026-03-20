# ──────────────────────────────────────────────────────────────────────
# Build from repository ROOT (the COPY commands reference root-level files):
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

COPY . .

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "-m", "services.ingest.ingest_worker"]
