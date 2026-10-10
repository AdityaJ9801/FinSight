# FinSight API + Celery Worker unified root Dockerfile
# Builds the backend application from repository root for direct Docker builds and CI/CD registries.
FROM python:3.12-slim-bookworm

WORKDIR /app

# Minimal system deps for OCR, curl for healthchecks, and OpenMP math acceleration
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY backend/ .

ENV FLASK_APP=run.py \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000

EXPOSE 5000

HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

CMD ["sh", "-c", "gunicorn run:app --bind 0.0.0.0:${PORT} --workers 2 --worker-class gthread --threads 8 --timeout 600"]
