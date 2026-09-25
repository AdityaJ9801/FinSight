import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'instance' / 'finsight.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # SQLite + Celery threads: avoid pooled connections outliving a worker thread.
        "pool_pre_ping": True,
    }

    STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", BASE_DIR / "instance" / "storage"))

    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    # "auto" (default): picks whichever provider has an API key configured, checked in
    # this order -- openai, gemini, custom (LLM_API_KEY) -- falling back to "fake" if none
    # do. Set explicitly ("fake" | "real" | "openai" | "gemini") to pin one regardless of
    # what keys are present. See app/llm_gateway/__init__.py's resolve_backend().
    LLM_BACKEND = os.environ.get("LLM_BACKEND", "auto")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "custom-model")
    LLM_EMBEDDINGS_ENABLED = _bool("LLM_EMBEDDINGS_ENABLED", "false")

    # OpenAI models: default fast/standard model (gpt-4o-mini) and reasoning/advanced model (gpt-4o)
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL_NAME = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini")
    OPENAI_REASONING_MODEL_NAME = os.environ.get("OPENAI_REASONING_MODEL_NAME", "gpt-4o")

    # Gemini models: default fast model (gemini-2.0-flash) and reasoning/pro model (gemini-1.5-pro)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.0-flash")
    GEMINI_REASONING_MODEL_NAME = os.environ.get("GEMINI_REASONING_MODEL_NAME", "gemini-1.5-pro")

    # Master switch: true = up to LLM_MAX_CONCURRENT_REQUESTS calls may be in flight at once
    # across agents/threads. Enabled by default for hosted models (OpenAI/Gemini).
    LLM_PARALLEL_CALLS = _bool("LLM_PARALLEL_CALLS", "true")
    LLM_MAX_CONCURRENT_REQUESTS = int(os.environ.get("LLM_MAX_CONCURRENT_REQUESTS", "5"))
    LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "8192"))

    WEB_SEARCH_ENABLED = _bool("WEB_SEARCH_ENABLED", "true")
    WEB_SEARCH_NUM_RESULTS = int(os.environ.get("WEB_SEARCH_NUM_RESULTS", "3"))
    WEB_SEARCH_LINES_PER_RESULT = int(os.environ.get("WEB_SEARCH_LINES_PER_RESULT", "6"))
    WEB_SEARCH_TIMEOUT_S = int(os.environ.get("WEB_SEARCH_TIMEOUT_S", "10"))

    OCR_ENABLED = _bool("OCR_ENABLED", "false")

    MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200MB per upload request
    MAX_REPLANS = 2
    MAX_REPORT_REVISIONS = 2
    REVIEW_CONFIDENCE_THRESHOLD = 0.85
    # If true, low-confidence row mappings flag gaps but allow automated pipeline progress
    AUTO_APPROVE_LOW_CONFIDENCE = _bool("AUTO_APPROVE_LOW_CONFIDENCE", "true")
    # A reconciliation check failing by less than this (relative to the expected value) logs
    # a gap and lets the pipeline continue instead of blocking at AWAITING_REVIEW -- e.g. a
    # subset chart-of-accounts missing a granular Schedule III caption (minority interest,
    # share of associates' profit, ...) will legitimately leave a bounded gap in a formula
    # like "recomputed PAT = stated PAT" that isn't a data error. A NO_FACTS check (empty
    # dataset) always blocks regardless of this setting -- there's no "small" version of that.
    RECONCILIATION_MATERIALITY_PCT = float(os.environ.get("RECONCILIATION_MATERIALITY_PCT", "0.15"))

