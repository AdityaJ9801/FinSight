# ==============================================================================
# FinSight All-in-One Dockerfile (Render Free-Tier 1-Go Deployment)
# Runs Frontend (Nginx), Backend (Gunicorn), Worker (Celery), and Redis in 1 container.
# ==============================================================================

# Stage 1: Build the React frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Unified runtime container (Python 3.12 + Redis + Nginx)
FROM python:3.12-slim-bookworm

WORKDIR /app

# System dependencies:
# - redis-server: embedded background broker for Celery
# - nginx & gettext-base: web server (serves React frontend, proxies /api, handles $PORT)
# - tesseract-ocr: OCR table extraction
# - libgomp1: OpenMP math acceleration
# - curl: healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    redis-server \
    nginx \
    gettext-base \
    curl \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
COPY backend/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy backend source code
COPY backend/ ./

# Copy compiled frontend from Stage 1 into Nginx webroot
COPY --from=frontend-builder /web/dist /usr/share/nginx/html

# Copy Nginx template and startup script
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Environment variables
ENV FLASK_APP=run.py \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000 \
    CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
    CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1 \
    DATABASE_URL=sqlite:////app/instance/finsight.db \
    STORAGE_ROOT=/app/instance/storage \
    LLM_BACKEND=auto \
    AUTO_APPROVE_LOW_CONFIDENCE=true

EXPOSE 10000

# Health check tests Nginx which proxies to Flask API
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-10000}/api/health || exit 1

ENTRYPOINT ["/app/start.sh"]
