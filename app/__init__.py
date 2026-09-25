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

    app.register_blueprint(jobs_bp, url_prefix="/api/jobs")
    app.register_blueprint(review_bp, url_prefix="/api/review")
    app.register_blueprint(results_bp, url_prefix="/api/jobs")
    app.register_blueprint(reports_bp, url_prefix="/api/jobs")
    app.register_blueprint(qa_bp, url_prefix="/api/qa")
    app.register_blueprint(search_bp, url_prefix="/api/search")
    app.register_blueprint(llm_bp, url_prefix="/api/llm")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    from app.cli import register_cli

    register_cli(app)

    return app
