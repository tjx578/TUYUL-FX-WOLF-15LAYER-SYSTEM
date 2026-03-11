FROM python:3.12-slim

WORKDIR /app

# IMPORTANT: build with repository root as Docker context.
# This Dockerfile path should be used with context `.` so root files exist.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn services.api.main:app --host 0.0.0.0 --port 8000"]
