"""Job blackboard: named artifacts that agents publish and other agents consume (design doc
§4.3's JobState-as-blackboard). Agents never message each other directly -- one agent
writes an artifact here, the supervisor schedules its dependents, and they read it back.

Every artifact key maps to one fixed storage path under the job's folder, so the rest of
the system (API endpoints, Q&A, renderers) finds them by name instead of each re-deriving
f"{job_id}/delivery/....json" strings that could drift apart.
"""
from __future__ import annotations

import json
from typing import Any

from app.utils import storage

ARTIFACTS: dict[str, str] = {
    "insights": "delivery/insights.json",        # InsightReasonerAgent: ranked insights + metrics/findings context
    "charts": "delivery/charts.json",            # ChartSpecAgent: rendered charts (PNG base64 + spec + caption)
    "draft": "delivery/draft.json",              # ReportWriterAgent: placeholder draft + deterministic appendices
    "forecast": "analysis/forecast.json",        # ForecastAgent: forecast values + uncertainty range per series
    "detailed_analysis": "analysis/detailed.json",  # DetailedAnalyticsAgent: statement/DuPont/bridge/bank analytics
}


def path(job_id: str, key: str) -> str:
    return f"{job_id}/{ARTIFACTS[key]}"


def uri(job_id: str, key: str) -> str:
    return f"file://{path(job_id, key)}"


def exists(job_id: str, key: str) -> bool:
    return storage.resolve(path(job_id, key)).exists()


def write(job_id: str, key: str, payload: Any) -> str:
    return storage.write_text(path(job_id, key), json.dumps(payload, default=str))


def read(job_id: str, key: str, default: Any = None) -> Any:
    """Missing or unreadable artifacts return `default` -- "not produced yet" is a normal
    state for most consumers (e.g. Q&A asked before delivery ran)."""
    try:
        return json.loads(storage.resolve(path(job_id, key)).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default
