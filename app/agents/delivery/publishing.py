"""Final report assembly + rendering, shared by every path that produces a report: the
delivery stage (verified or not) and the chat assistant's on-demand report_writer re-run.

These three paths used to each carry their own copy of "append the diagnostic section,
interleave charts, render HTML/DOCX/PDF" and had already drifted. Section order is fixed
here: verified narrative -> Detailed Statement Analysis tables -> Data Diagnostic.
The deterministic appendices are added after verification: they're computed from the
database, not written by the LLM, so there's nothing in them for the verifier to check.
"""
from __future__ import annotations

from app.domain.detailed_analysis_section import build_detailed_analysis_section
from app.extensions import db
from app.models.report import Report
from app.orchestrator import blackboard
from app.tools.report_render import render_docx, render_html, render_pdf, resolve_placeholders
from app.utils.ids import new_id

UNVERIFIED_WARNING = {
    "heading": "⚠ Not Verified",
    "body": "This report did not pass automated verification and should be reviewed by an analyst before "
            "relying on it -- it's provided here so there's something to inspect in the meantime, not as a "
            "final, checked report. See the job's task trace for what the verifier flagged.",
}


def resolve_draft_sections(draft: dict, dataset_version_id: str) -> list[dict]:
    """Best-effort placeholder resolution when the verifier produced nothing usable."""
    out = []
    for section in draft.get("sections", []):
        body, _ = resolve_placeholders(section["body"], dataset_version_id)
        out.append({**section, "body": body})
    return out


def appendix_sections(job_id: str, draft: dict | None) -> list[dict]:
    sections = []
    tables_section = build_detailed_analysis_section(job_id)
    if tables_section:
        sections.append(tables_section)
    draft = draft or {}
    if draft.get("data_diagnostic_section"):
        sections.append(draft["data_diagnostic_section"])
    elif draft.get("data_quality_section"):
        sections.append(draft["data_quality_section"])
    return sections


def publish_report(job, dataset_version_id: str, narrative_sections: list[dict], verified: bool,
                   draft_uri: str | None, report: Report | None = None) -> Report:
    """Renders HTML/DOCX/PDF and records them on a Report row (a new one unless `report` is
    given). Caller commits."""
    draft = blackboard.read(job.id, "draft") or {}
    charts = blackboard.read(job.id, "charts") or []
    title = draft.get("title") or ("Financial Analysis Report" if verified else "Draft Report (Unverified)")

    sections = ([] if verified else [UNVERIFIED_WARNING]) + list(narrative_sections) + appendix_sections(job.id, draft)
    html_result = render_html(job.id, title, sections, charts)
    docx_uri = render_docx(job.id, title, sections, charts)
    pdf_uri = render_pdf(job.id, html_result["html"])

    if report is None:
        report = Report(id=new_id("rep_"), dataset_version=dataset_version_id, template=job.plan_template)
        db.session.add(report)
    report.draft_uri = draft_uri
    report.html_uri = html_result["html_uri"]
    report.docx_uri = docx_uri
    report.pdf_uri = pdf_uri
    report.verifier_status = "pass" if verified else "failed"
    return report
