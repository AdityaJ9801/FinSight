from flask import Flask
from flask_cors import CORS
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.config import Config
from app.extensions import db


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    """WAL mode + a busy timeout so concurrent stage-supervisor threads writing to SQLite
    (see agents/data/supervisor.py's ThreadPoolExecutor fan-out) retry instead of
    immediately raising 'database is locked'. No-ops on non-SQLite connections."""
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


def _register_error_handlers(app: Flask) -> None:
    """Every API failure is JSON with an `error` the UI can show as-is. Without this, an
    outage at the model provider surfaced as Werkzeug's HTML debugger page (or a bare 500),
    which the client could only report as "Request failed"."""
    from urllib.parse import urlparse

    import requests
    from flask import jsonify, request
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(requests.RequestException)
    def llm_unavailable(exc: requests.RequestException):
        response = getattr(exc, "response", None)
        host = urlparse(getattr(response, "url", None) or getattr(exc.request, "url", "") or "").netloc or "the model provider"
        if response is not None:
            what = f"returned {response.status_code} {response.reason or ''}".strip()
        elif isinstance(exc, requests.Timeout):
            what = "timed out"
        else:
            what = "couldn't be reached"
        app.logger.warning("LLM call failed: %s", exc)
        return jsonify(error=f"The language model at {host} {what}. Nothing was changed. Try again shortly, "
                             f"or switch provider under Model & keys."), 502

    @app.errorhandler(Exception)
    def unexpected(exc: Exception):
        if isinstance(exc, HTTPException):
            if request.path.startswith("/api/"):
                return jsonify(error=exc.description or exc.name), exc.code
            return exc
        app.logger.exception("Unhandled error on %s", request.path)
        return jsonify(error="Something went wrong on the server and the request wasn't completed. "
                             "The details are in the API log."), 500


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    CORS(app)

    from app import models  # noqa: F401  (registers models with SQLAlchemy metadata)

    from app.api.jobs import bp as jobs_bp
    from app.api.qa import bp as qa_bp
    from app.api.reports import bp as reports_bp
    from app.api.results import bp as results_bp
    from app.api.review import bp as review_bp
    from app.api.search import bp as search_bp
    from app.api.llm_config import bp as llm_bp
    from app.api.benchmarks import bp as benchmarks_bp

    app.register_blueprint(jobs_bp, url_prefix="/api/jobs")
    app.register_blueprint(review_bp, url_prefix="/api/review")
    app.register_blueprint(results_bp, url_prefix="/api/jobs")
    app.register_blueprint(reports_bp, url_prefix="/api/jobs")
    app.register_blueprint(qa_bp, url_prefix="/api/qa")
    app.register_blueprint(search_bp, url_prefix="/api/search")
    app.register_blueprint(llm_bp, url_prefix="/api/llm")
    app.register_blueprint(benchmarks_bp, url_prefix="/api/benchmarks")
    from app.api.agents import bp as agents_bp

    app.register_blueprint(agents_bp, url_prefix="/api/agents")

    # job_profiles was added after the initial schema. `flask init-db` creates it, but an
    # existing database that hasn't re-run init-db would 500 on every job endpoint -- so
    # create just this table if it's missing (checkfirst makes it a no-op otherwise).
    if not app.config.get("TESTING"):
        with app.app_context():
            try:
                from app.models.job import JobProfile

                JobProfile.__table__.create(bind=db.engine, checkfirst=True)
            except Exception as exc:  # the database may not exist yet (before init-db)
                app.logger.debug("job_profiles check skipped: %s", exc)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    _register_error_handlers(app)

    from app.cli import register_cli

    register_cli(app)

    return app
