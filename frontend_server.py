"""Serves the plain HTML/CSS/JS sample frontend (frontend/) as static files via FastAPI.

Deliberately thin: this process does nothing but serve static assets. The frontend's own
JavaScript (frontend/app.js) talks directly to the Flask API over HTTP (CORS is already
enabled there -- see app/__init__.py's CORS(app)), so there's no proxying/business logic
here and the existing, already-tested Flask backend is untouched.

Run with: uvicorn frontend_server:app --host 0.0.0.0 --port 8080
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).parent / "frontend"

app = FastAPI(title="FinSight Sample Frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
