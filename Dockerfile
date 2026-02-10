# Wolf 15-Layer Trading System - Dockerfile (Multi-stage build)

FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/storage/snapshots /app/storage/ea_commands /app/storage/ea_state /app/logs

# ================================================
# Stage: API Server
# ================================================
FROM base AS api
EXPOSE 8000
CMD ["gunicorn", "api_server:app", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]

# ================================================
# Stage: Trading Engine
# ================================================
FROM base AS engine
CMD ["python", "main.py"]

# ================================================
# Stage: Ingest Service
# ================================================
FROM base AS ingest
CMD ["python", "-m", "ingest.finnhub_ws"]
