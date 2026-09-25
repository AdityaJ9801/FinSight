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
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
