# Friday 2.0 - FastAPI Gateway
# Multi-stage build: dev + production

# ============================================
# Base stage - shared dependencies
# ============================================
FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Development stage - hot reload
# ============================================
FROM base AS dev

ENV ENVIRONMENT=development
ENV LOG_LEVEL=DEBUG

# Install dev dependencies
RUN pip install --no-cache-dir pytest pytest-asyncio pytest-cov httpx

COPY . .

CMD ["uvicorn", "run:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ============================================
# Production stage - optimized
# ============================================
FROM base AS production

ENV ENVIRONMENT=production
ENV LOG_LEVEL=INFO

COPY . .

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "run:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
