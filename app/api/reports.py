from flask import Blueprint, jsonify, request, send_file

from app.api.deps import current_tenant_id
from app.models.job import Job
from app.models.report import Report
from app.utils import storage

bp = Blueprint("reports", __name__)

_URI_FIELD = {"html": "html_uri", "docx": "docx_uri", "pdf": "pdf_uri"}
_MIME = {
    "html": "text/html",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@bp.get("/<job_id>/report")
def get_report(job_id):
    job = Job.query.filter_by(id=job_id, tenant_id=current_tenant_id()).first()
    if job is None or job.dataset_version_id is None:
        return jsonify(error="not found"), 404

    report = Report.query.filter_by(dataset_version=job.dataset_version_id).order_by(Report.created_at.desc()).first()
    if report is None:
        return jsonify(error="report not generated yet"), 404

    fmt = request.args.get("format", "html")
    if fmt not in _URI_FIELD:
        return jsonify(error="format must be html, docx, or pdf"), 400

    uri = getattr(report, _URI_FIELD[fmt])
    if not uri:
        return jsonify(error=f"{fmt} not available for this report (verifier_status={report.verifier_status})"), 404

    return send_file(storage.resolve(uri), mimetype=_MIME[fmt], as_attachment=(fmt != "html"),
                      download_name=f"report.{fmt}")
