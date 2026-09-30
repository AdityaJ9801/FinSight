"""Serves the built React frontend (frontend/dist) and proxies /api to the Flask API.

The browser only ever talks to this one origin: static assets and client-side routes
(/analyses/<id>, /settings, ...) are served from the Vite build, and every /api/* request is
forwarded to Flask. That keeps the frontend free of hardcoded API hosts and CORS concerns,
and works the same natively and in Docker (where Flask is reachable as http://api:5000).

Build the frontend first:  cd frontend && npm ci && npm run build
Run with:                  uvicorn frontend_server:app --host 0.0.0.0 --port 8080
Environment:               FINSIGHT_API_URL (default http://127.0.0.1:5000)
"""
import os
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

DIST_DIR = Path(__file__).parent / "frontend" / "dist"
API_URL = os.environ.get("FINSIGHT_API_URL", "http://127.0.0.1:5000").rstrip("/")

# Hop-by-hop headers must not be forwarded by a proxy (RFC 7230 §6.1); content-length/encoding
# are recomputed because `requests` hands back the already-decoded body.
_DROP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length", "host"}

app = FastAPI(title="FinSight Web")
_session = requests.Session()


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def proxy_api(path: str, request: Request) -> Response:
    body = await request.body()
    try:
        # requests is blocking; run it in the threadpool so a long agent re-run doesn't stall other requests.
        upstream = await run_in_threadpool(
            _session.request,
            request.method,
            f"{API_URL}/api/{path}",
            params=list(request.query_params.multi_items()),
            data=body,
            headers={k: v for k, v in request.headers.items() if k.lower() not in _DROP_HEADERS},
            timeout=600,
        )
    except requests.ConnectionError:
        return Response('{"error": "The FinSight API is not reachable."}', status_code=502, media_type="application/json")
    headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_HEADERS}
    return Response(upstream.content, status_code=upstream.status_code, headers=headers)


if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if not (DIST_DIR / "index.html").is_file():
        return HTMLResponse(
            "<h1>Frontend not built</h1><p>Run <code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code>.</p>",
            status_code=503,
        )
    candidate = (DIST_DIR / path).resolve()
    if path and candidate.is_file() and DIST_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)
    # Any other path is a client-side route; the React router takes it from here.
    return FileResponse(DIST_DIR / "index.html")
