import json

from flask import Blueprint, jsonify

from app.api.deps import current_tenant_id
from app.models.finding import Finding
from app.models.job import Job
from app.models.metric import Metric
from app.models.validation import ValidationResult
from app.utils import storage

bp = Blueprint("results", __name__)


def _scoped_job(job_id: str) -> Job | None:
    return Job.query.filter_by(id=job_id, tenant_id=current_tenant_id()).first()


@bp.get("/<job_id>/metrics")
def get_metrics(job_id):
    job = _scoped_job(job_id)
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404
    rows = Metric.query.filter_by(dataset_version=job.dataset_version_id).order_by(Metric.metric_code, Metric.period_end).all()
    return jsonify([{
        "id": m.id, "metric_code": m.metric_code, "period_end": m.period_end.isoformat(),
        "value": float(m.value) if m.value is not None else None, "unit": m.unit,
    } for m in rows])


@bp.get("/<job_id>/findings")
def get_findings(job_id):
    job = _scoped_job(job_id)
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404
    rows = Finding.query.filter_by(dataset_version=job.dataset_version_id).all()
    return jsonify([{
        "id": f.id, "module": f.module, "severity": f.severity, "title": f.title,
        "body": f.body, "metric_ids": f.metric_ids, "confidence": f.confidence,
    } for f in rows])


@bp.get("/<job_id>/charts")
def get_charts(job_id):
    """Read-only: the same chart images/captions already embedded in the rendered report
    (ChartSpecAgent writes them to <job_id>/delivery/charts.json), exposed separately so a
    frontend can show a chart gallery without parsing the report HTML. Empty list (not 404)
    before the delivery stage has run -- "no charts yet" is a normal, expected state, not
    an error."""
    job = _scoped_job(job_id)
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404
    try:
        charts = json.loads(storage.resolve(f"{job_id}/delivery/charts.json").read_text())
    except FileNotFoundError:
        return jsonify([])
    return jsonify([{
        "chart_id": c["chart_id"], "title": c["title"], "caption": c.get("caption", ""),
        "png_base64": c["png_base64"],
    } for c in charts])


@bp.get("/<job_id>/validation")
def get_validation(job_id):
    job = _scoped_job(job_id)
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404
    rows = ValidationResult.query.filter_by(dataset_version=job.dataset_version_id).all()
    return jsonify([{
        "check_code": r.check_code, "status": r.status,
        "expected": float(r.expected) if r.expected is not None else None,
        "actual": float(r.actual) if r.actual is not None else None,
        "diff": float(r.diff) if r.diff is not None else None, "details": r.details,
    } for r in rows])
