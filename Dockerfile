# Dockerfile — KLG AI OS (Alfred + Bloodhound)
#
# Two-stage build:
#   Stage 1 (node-builder): installs Node 20, runs npm ci + npm run build
#   Stage 2 (final):        Python 3.12-slim + compiled React dist
#
# Local test:
#   docker build -t klg-ai-os .
#   docker run --env-file .env -p 8000:8000 klg-ai-os

# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS node-builder

WORKDIR /build

COPY web-next/package.json web-next/package-lock.json* ./
RUN npm ci

COPY web-next/ ./
RUN npm run build
# Output: /build/dist/

# ── Stage 2: Python app + compiled frontend ───────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caches unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source (excludes web-next/node_modules via .dockerignore)
COPY . .

# Drop the compiled React dist into the location main.py checks first
COPY --from=node-builder /build/dist/ ./web-next/dist/

# Railway injects PORT automatically. Default 8000 for local runs.
ENV PORT=8000

# Single worker — APScheduler must run in one process only.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
