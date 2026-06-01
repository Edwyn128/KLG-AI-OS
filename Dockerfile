# Dockerfile — KLG AI OS (Alfred + Bloodhound)
#
# Builds a minimal production image. The Azure App Service deployment
# pipeline (GitHub Actions) builds this image and pushes it to Azure
# Container Registry, then App Service pulls and runs it.
#
# Local test:
#   docker build -t klg-ai-os .
#   docker run --env-file .env -p 8000:8000 klg-ai-os

FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caches unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Azure App Service injects PORT via environment variable.
# Default 8000 for local runs.
ENV PORT=8000

# Two workers handles the background APScheduler + inbound requests
# without needing a separate process. Scale up in Azure if needed.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2"]
