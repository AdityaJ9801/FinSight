from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from flask import Flask

from app.agents.base import AgentResult, Status, TaskSpec
from app.agents.delivery.chart_spec import ChartSpecAgent
from app.agents.delivery.insight import InsightReasonerAgent
from app.agents.delivery.report_writer import ReportWriterAgent
from app.agents.verifier import VerifierAgent
from app.domain.taxonomy import interleave_charts_into_sections
from app.extensions import db
from app.models.report import Report
from app.tools.report_render import render_docx, render_html, render_pdf, resolve_placeholders
from app.utils import storage
from app.utils.ids import new_id


def _spec(job_id: str, tenant_id: str, agent_name: str, params: dict) -> TaskSpec:
    # Takes plain job_id/tenant_id strings, not the Job ORM object -- ChartSpecAgent below
    # runs in its own thread with its own app context/session, and a SQLAlchemy instance
    # loaded in the main thread's session is not safe to touch from another thread (an
    # expired attribute access there triggers a lazy-refresh query against a session
    # another thread may be using at the same moment). Confirmed as a real, intermittent
    # failure (~40% of runs) before this fix.
    return TaskSpec(task_id=new_id("t_"), job_id=job_id, tenant_id=tenant_id, agent=agent_name,
                     goal=f"{agent_name} for job {job_id}", params=params)


class DeliverySupervisor:
    name = "delivery_supervisor"
    MAX_REVISIONS = 2

    def __init__(self, app: Flask, llm):
        self.app = app
        self.llm = llm

    def run_stage(self, job, dataset_version_id: str, guidance: dict[str, str] | None = None) -> bool:
        """guidance: {agent_name: note} from orchestrator.apply_pending_instructions, e.g.
        {"insight_reasoner": "...", "report_writer": "..."}."""
        job_id, tenant_id = job.id, job.tenant_id  # plain strings -- see _spec's docstring
        guidance = guidance or {}

        job.set_progress(88, "Generating insights")
        db.session.commit()

        insight_error: str | None = None
        insights_uri = None
        try:
            insight_result = InsightReasonerAgent(self.llm).run(_spec(job_id, tenant_id, "insight_reasoner",
                {"dataset_version_id": dataset_version_id, "user_guidance": guidance.get("insight_reasoner")}))
            insights_uri = insight_result.outputs[0].uri if insight_result.outputs else None
            if insights_uri is None:
                insight_error = insight_result.summary or "insight_reasoner produced no output"
        except Exception as exc:
            insight_error = str(exc)

        if insights_uri is None:
            # Unlike a mapping gap, there's no meaningful placeholder for "the model's
            # synthesized insights" -- surface this clearly and stop rather than pushing a
            # report through with no analysis behind it (or hanging indefinitely against a
            # dead LLM endpoint).
            job.status = "NEEDS_ANALYST"
            job.set_progress(88, f"Insight generation failed: {insight_error}")
            db.session.commit()
            return False

        job.set_progress(90, "Drafting report and charts")
        db.session.commit()

        def _run_chart_spec():
            # Own thread => own app context (SQLAlchemy sessions aren't thread-safe to
            # share), same as the data/analysis supervisors' fan-out.
            with self.app.app_context():
                return ChartSpecAgent(self.llm).run(_spec(
                    job_id, tenant_id, "chart_spec", {"dataset_version_id": dataset_version_id, "insights_uri": insights_uri}
                ))

        with ThreadPoolExecutor(max_workers=2) as pool:
            chart_future = pool.submit(_run_chart_spec)
            try:
                draft_result = ReportWriterAgent(self.llm).run(_spec(job_id, tenant_id, "report_writer",
                    {"dataset_version_id": dataset_version_id, "insights_uri": insights_uri,
                     "user_guidance": guidance.get("report_writer")}))
            except Exception as exc:
                draft_result = AgentResult(task_id=new_id("t_"), status=Status.FAILED,
                                            summary=f"report_writer failed unexpectedly: {exc}")
            try:
                chart_result = chart_future.result()
            except Exception as exc:
                # Charts are a nice-to-have on top of the report, not load-bearing -- a
                # chart-generation failure (e.g. an LLM timeout) shouldn't sink an otherwise
                # good report.
                chart_result = AgentResult(task_id=new_id("t_"), status=Status.FAILED,
                                            summary=f"chart_spec failed unexpectedly: {exc}")

        draft_uri = draft_result.outputs[0].uri if draft_result.outputs else None
        charts = json.loads(storage.resolve(chart_result.outputs[0].uri).read_text()) if chart_result.outputs else []

        job.set_progress(93, "Verifying report")
        db.session.commit()

        verified = False
        verifier_result = None
        for revision in range(self.MAX_REVISIONS + 1):
            if draft_uri is None:
                break
            try:
                verifier_result = VerifierAgent(self.llm).run(_spec(job_id, tenant_id, "verifier",
                    {"dataset_version_id": dataset_version_id, "draft_uri": draft_uri, "insights_uri": insights_uri}))
            except Exception as exc:
                verifier_result = AgentResult(task_id=new_id("t_"), status=Status.FAILED,
                                               summary=f"verifier failed unexpectedly: {exc}")
                break
            if verifier_result.status == Status.DONE:
                verified = True
                break
            if revision == self.MAX_REVISIONS:
                break
            # usage["feedback"] is only present for an LLM claim-check rejection; a
            # deterministic failure (unresolved placeholder, raw number) has no "feedback"
            # key at all, so fall back to the Issue messages, which describe exactly the
            # same thing in that case.
            feedback = verifier_result.usage.get("feedback") or [i.message for i in verifier_result.issues]
            draft_result = ReportWriterAgent(self.llm).run(_spec(job_id, tenant_id, "report_writer",
                {"dataset_version_id": dataset_version_id, "insights_uri": insights_uri,
                 "verifier_feedback": feedback, "user_guidance": guidance.get("report_writer")}))
            draft_uri = draft_result.outputs[0].uri if draft_result.outputs else None

        report = Report(id=new_id("rep_"), dataset_version=dataset_version_id, template=job.plan_template)

        if not verified:
            # Previously this left html_uri/docx_uri/pdf_uri all unset, so
            # GET /api/jobs/<id>/report 404'd forever -- a user landing on NEEDS_ANALYST had
            # nothing to download at all, even though a draft existed. Render a best-effort,
            # clearly-labeled UNVERIFIED version instead, so there's something to read/export
            # while an analyst looks at why verification failed.
            resolved_sections = (verifier_result.usage.get("resolved_sections") if verifier_result else None) or []
            if not resolved_sections and draft_uri:
                # The verifier crashed outright (supervisor's except-Exception path) before
                # producing even its own best-effort resolution -- resolve the raw draft
                # ourselves so a download still exists rather than nothing.
                fallback_draft = json.loads(storage.resolve(draft_uri).read_text())
                for section in fallback_draft.get("sections", []):
                    resolved_text, _ = resolve_placeholders(section["body"], dataset_version_id)
                    resolved_sections.append({"heading": section["heading"], "body": resolved_text})

            report.verifier_status = "failed"
            report.draft_uri = draft_uri
            if resolved_sections:
                warning_section = {
                    "heading": "⚠ Not Verified",
                    "body": "This report did not pass automated verification and should be "
                            "reviewed by an analyst before relying on it -- it's provided here "
                            "so there's something to inspect in the meantime, not as a final, "
                            "checked report. See the job's task trace for what the verifier flagged.",
                }
                draft_title = "Draft Report (Unverified)"
                if draft_uri:
                    draft_title = json.loads(storage.resolve(draft_uri).read_text()).get("title", draft_title)
                all_sections = [warning_section] + resolved_sections
                interleaved_sections, _ = interleave_charts_into_sections(all_sections, charts)
                html_result = render_html(job.id, draft_title, interleaved_sections, charts)
                docx_uri = render_docx(job.id, draft_title, interleaved_sections, charts)
                pdf_uri = render_pdf(job.id, html_result["html"])
                report.html_uri = html_result["html_uri"]
                report.docx_uri = docx_uri
                report.pdf_uri = pdf_uri

            db.session.add(report)
            job.status = "NEEDS_ANALYST"
            job.set_progress(95, "Verifier could not pass the draft after revisions; an unverified "
                                 "draft report is available for download")
            db.session.commit()
            return False

        resolved_sections = verifier_result.usage["resolved_sections"]
        draft = json.loads(storage.resolve(draft_uri).read_text())
        # Appended after verification, not part of the LLM-authored/verified draft -- see
        # ReportWriterAgent._data_quality_section's docstring for why.
        if draft.get("data_quality_section"):
            resolved_sections = resolved_sections + [draft["data_quality_section"]]
        interleaved_sections, _ = interleave_charts_into_sections(resolved_sections, charts)
        html_result = render_html(job.id, draft["title"], interleaved_sections, charts)
        docx_uri = render_docx(job.id, draft["title"], interleaved_sections, charts)
        pdf_uri = render_pdf(job.id, html_result["html"])

        report.verifier_status = "pass"
        report.draft_uri = draft_uri
        report.html_uri = html_result["html_uri"]
        report.docx_uri = docx_uri
        report.pdf_uri = pdf_uri
        db.session.add(report)
        job.status = "COMPLETED"
        job.set_progress(100, "Report ready")
        db.session.commit()
        return True
