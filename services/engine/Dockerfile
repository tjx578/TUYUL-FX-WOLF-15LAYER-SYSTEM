FROM python:3.12-slim

WORKDIR /app

# IMPORTANT: build with repository root as Docker context.
# This Dockerfile path should be used with context `.` so root files exist.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

CMD ["sh", "-c", "alembic upgrade head && python -m services.engine.runner"]
