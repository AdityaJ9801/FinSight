from flask import Blueprint, jsonify, request

from app.api.deps import current_tenant_id
from app.models.finding import Finding
from app.domain.benchmarks import compare as compare_to_benchmarks
from app.extensions import db
from app.models.job import Job, JobProfile
from app.models.metric import Metric
from app.models.validation import ValidationResult
from app.tools.calc.health_score import compute_health_score
from app.orchestrator import blackboard

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
    (ChartSpecAgent publishes them to the job blackboard as `charts`), exposed separately so a
    frontend can show a chart gallery without parsing the report HTML. Empty list (not 404)
    before the delivery stage has run -- "no charts yet" is a normal, expected state, not
    an error."""
    job = _scoped_job(job_id)
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404
    charts = blackboard.read(job_id, "charts") or []
    return jsonify([{
        "chart_id": c["chart_id"], "title": c["title"], "caption": c.get("caption", ""),
        "png_base64": c["png_base64"], "takeaway": c.get("takeaway", ""), "section_key": c.get("section_key"),
    } for c in charts])


@bp.get("/<job_id>/analysis")
def get_detailed_analysis(job_id):
    """Detailed statement analysis (YoY/common-size, DuPont, CAGR, profit bridge, net debt,
    bank flows) from the DetailedAnalyticsAgent. 404 until the analysis stage has run."""
    job = _scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    analysis = blackboard.read(job_id, "detailed_analysis")
    if analysis is None:
        return jsonify(error="detailed analysis not produced yet"), 404
    return jsonify(analysis)


@bp.get("/<job_id>/health")
def get_health(job_id):
    """The same rules-table health score the insight reasoner and report use, computed
    over each metric's latest period -- exposed so the UI can show it without parsing the report."""
    job = _scoped_job(job_id)
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404
    latest: dict[str, float] = {}
    rows = Metric.query.filter_by(dataset_version=job.dataset_version_id).order_by(Metric.period_end).all()
    for m in rows:
        if m.value is not None:
            latest[m.metric_code] = float(m.value)
    if not latest:
        return jsonify(error="no metrics yet"), 404
    score = compute_health_score(latest)
    if not any(b["included"] for b in score["breakdown"]):
        # e.g. a bank-statement-only analysis: none of the scored statement ratios exist, and
        # "0 / 100, Poor" would read as a verdict on the company rather than missing inputs.
        return jsonify(error="the health score needs balance sheet and P&L ratios"), 404
    return jsonify(score)


@bp.get("/<job_id>/benchmarks")
def get_benchmarks(job_id):
    """The job's latest ratios placed against industry quartiles. ?industry= overrides the
    industry saved on the analysis profile; without either there is nothing to compare to."""
    job = _scoped_job(job_id)
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404
    profile = db.session.get(JobProfile, job_id)
    industry = request.args.get("industry") or (profile.industry if profile else None)
    if not industry:
        return jsonify(error="choose an industry to compare against"), 400
    latest: dict[str, tuple[str, float, str]] = {}
    for m in Metric.query.filter_by(dataset_version=job.dataset_version_id).order_by(Metric.period_end).all():
        if m.value is not None:
            latest[m.metric_code] = (m.period_end.isoformat(), float(m.value), m.unit)
    result = compare_to_benchmarks(industry, latest)
    if result is None:
        return jsonify(error=f"unknown industry '{industry}'"), 400
    return jsonify(result)


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


@bp.get("/<job_id>/data-explorer")
def get_data_explorer(job_id):
    """Dynamically inspects what attributes are present in the uploaded data and returns
    them formatted in both Row format (horizontal statement layout) and Column format
    (transposed columnar layout)."""
    job = _scoped_job(job_id)
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404
    from app.domain.data_explorer import inspect_dataset_attributes
    data = inspect_dataset_attributes(job_id, job.dataset_version_id)
    return jsonify(data)
