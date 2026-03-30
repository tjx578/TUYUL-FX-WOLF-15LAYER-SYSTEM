FROM python:3.11-slim

LABEL maintainer="TUYUL Trading Swarm"
LABEL version="3.0.0"
LABEL description="Production-grade multi-agent AI trading system"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir \
    fastapi uvicorn[standard] pydantic redis[hiredis] loguru PyJWT \
    python-multipart httpx python-dotenv aiofiles pyyaml

# Copy source
COPY . .

# Create storage dirs
RUN mkdir -p storage/journal storage/ea_commands storage/ea_state

# Non-root user
RUN useradd -m -u 1000 tuyul && chown -R tuyul:tuyul /app
USER tuyul

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD ["python", "main.py"]
