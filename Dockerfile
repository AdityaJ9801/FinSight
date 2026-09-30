# --- Stage 1: build the React frontend (frontend/ -> frontend/dist) ---
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime for the API, worker and web server ---
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
COPY --from=web /web/dist ./frontend/dist

ENV FLASK_APP=run.py \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
