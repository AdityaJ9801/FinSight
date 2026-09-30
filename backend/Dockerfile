# FinSight API + Celery worker image. The same image runs both; docker-compose (or your
# platform) picks the command: the API by default, `celery -A app.workers.celery_app worker`
# for the worker, and `flask init-db` once to create the schema.
FROM python:3.12-slim

WORKDIR /app

# System deps for the parsing/ML/rendering stack: pdfplumber/PyMuPDF/matplotlib/
# scikit-learn/statsmodels all ship manylinux wheels for this base image, so this stays
# minimal -- just what a couple of them need at import/runtime, not a full build toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=run.py \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000

EXPOSE 5000

# gthread workers: the live-progress SSE endpoint holds a thread open while it polls, and
# chat-triggered agent re-runs can take minutes, hence threads plus a long timeout.
# PORT is honoured so platforms that inject one (Render, Railway, Cloud Run) work unchanged.
CMD ["sh", "-c", "gunicorn run:app --bind 0.0.0.0:${PORT} --workers 2 --worker-class gthread --threads 8 --timeout 600"]
