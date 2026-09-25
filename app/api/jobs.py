import hashlib
import json
import time

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from werkzeug.utils import secure_filename

from app.agents.base import TaskSpec
from app.agents.schemas import AssistantDecision
from app.api.deps import current_tenant_id, current_user_id
from app.extensions import db
from app.llm_gateway import get_llm_gateway, prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.audit import AuditLog
from app.models.bank import BankTransaction
from app.models.dataset import DatasetVersion, FinancialFact
from app.models.document import Document
from app.models.finding import Finding
from app.models.gst import GstReturn
from app.models.job import Job, JobInstruction, TaskRun
from app.models.metric import Metric
from app.models.report import Report
from app.models.review import ReviewItem
from app.models.validation import ValidationResult
from app.agents.delivery.chart_spec import ChartSpecAgent
from app.agents.delivery.insight import InsightReasonerAgent
from app.agents.delivery.report_writer import ReportWriterAgent
from app.agents.verifier import VerifierAgent
from app.orchestrator.orchestrator import QueueUnavailableError, STAGE_AGENT_DESCRIPTIONS, create_job, start
from app.orchestrator.templates import modules_for
from app.tools.report_render import render_docx, render_html, render_pdf, resolve_placeholders
from app.utils import storage
from app.utils.ids import new_id

bp = Blueprint("jobs", __name__)


@bp.post("")
def create_and_start_job():
    tenant_id = current_tenant_id()
    goal = request.form.get("goal", "Full financial analysis")
    plan_template = request.form.get("plan_template", "full_analysis")
    entity_id = request.form.get("entity_id")
    files = request.files.getlist("files")

    if not files:
        return jsonify(error="at least one file is required (multipart field 'files')"), 400

    job = create_job(tenant_id, entity_id, current_user_id(), goal, plan_template)

    for file_storage in files:
        filename = secure_filename(file_storage.filename or "")
        if not filename:
            continue
        content = file_storage.read()
        sha256 = hashlib.sha256(content).hexdigest()

        existing = Document.query.filter_by(tenant_id=tenant_id, sha256=sha256).first()
        uri = storage.write_bytes(f"{job.id}/raw/{new_id()}_{filename}", content)
        db.session.add(Document(
            id=new_id("doc_"), tenant_id=tenant_id, entity_id=entity_id, job_id=job.id,
            file_uri=uri, original_filename=filename, sha256=sha256,
            mime=file_storage.mimetype, duplicate_of=existing.id if existing else None,
            status="uploaded",
        ))
    db.session.commit()

    try:
        start(job)
    except QueueUnavailableError as exc:
        return jsonify(job_id=job.id, status=job.status, error=str(exc)), 503
    return jsonify(job_id=job.id, status=job.status), 201


@bp.get("/<job_id>")
def get_job(job_id):
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    return jsonify(_job_dict(job))


@bp.delete("/<job_id>")
def delete_job(job_id):
    """Deletes a job and everything scoped to it -- documents, facts, metrics, findings,
    reports, review items, the task trace, and its on-disk file tree. A currently-running
    job can be deleted too: the Celery task chain already no-ops cleanly on a missing job
    (see run_data_stage/run_analysis_stage/run_delivery_stage's `if job is None: return`),
    so this just lets the in-flight task finish and discard its result rather than trying
    to cancel it -- simpler and safer than interrupting a worker mid-task."""
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404

    dataset_version_id = job.dataset_version_id
    if dataset_version_id:
        FinancialFact.query.filter_by(dataset_version=dataset_version_id).delete()
        BankTransaction.query.filter_by(dataset_version=dataset_version_id).delete()
        GstReturn.query.filter_by(dataset_version=dataset_version_id).delete()
        ValidationResult.query.filter_by(dataset_version=dataset_version_id).delete()
        Metric.query.filter_by(dataset_version=dataset_version_id).delete()
        Finding.query.filter_by(dataset_version=dataset_version_id).delete()
        Report.query.filter_by(dataset_version=dataset_version_id).delete()
        DatasetVersion.query.filter_by(id=dataset_version_id).delete()

    ReviewItem.query.filter_by(job_id=job_id).delete()
    TaskRun.query.filter_by(job_id=job_id).delete()
    Document.query.filter_by(job_id=job_id).delete()
    AuditLog.query.filter_by(job_id=job_id).delete()
    Job.query.filter_by(id=job_id).delete()
    db.session.commit()

    storage.delete_dir(job_id)
    return jsonify(status="deleted", job_id=job_id)


@bp.get("/<job_id>/stream")
def stream_job(job_id):
    tenant_id = current_tenant_id()

    def generate():
        last_payload = None
        for _ in range(600):  # ~10 minutes of polling at 1s, then the client reconnects
            # The Celery worker updates this row from a separate process/connection; without
            # ending the previous transaction, SQLite's session could keep serving a stale
            # snapshot from when this loop's connection was first opened.
            db.session.commit()
            job = Job.query.filter_by(id=job_id, tenant_id=tenant_id).first()
            if job is None:
                yield "event: error\ndata: not found\n\n"
                return
            payload = json.dumps(_job_dict(job))
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if job.status in ("COMPLETED", "FAILED", "NEEDS_ANALYST"):
                return
            time.sleep(1)

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@bp.get("/<job_id>/tasks")
def job_tasks(job_id):
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    runs = TaskRun.query.filter_by(job_id=job_id).order_by(TaskRun.created_at).all()
    return jsonify([{
        "id": r.id, "agent": r.agent, "status": r.status, "summary": r.summary,
        "confidence": r.confidence, "issues": r.issues, "created_at": r.created_at.isoformat(),
    } for r in runs])


@bp.post("/<job_id>/instructions")
def add_instruction(job_id):
    """Extra guidance/data the user provides WHILE the job is running (not the pre-run
    goal, not post-completion QA -- see /api/qa for that). Picked up by the orchestrator
    at the next stage boundary (orchestrator.apply_pending_instructions), not applied
    immediately -- there's no live channel into an already-executing Celery task, so this
    is a checkpoint-based mechanism, not a true interrupt. Works whether the job is
    currently running OR already finished a stage that's still relevant to a later one
    (e.g. sent while data-stage mapping is in progress, applied once analysis starts)."""
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    data = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify(error="content is required"), 400

    instruction = JobInstruction(id=new_id("instr_"), job_id=job_id, content=content)
    db.session.add(instruction)
    db.session.commit()
    return jsonify(id=instruction.id, status=instruction.status), 201


@bp.get("/<job_id>/instructions")
def list_instructions(job_id):
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    rows = JobInstruction.query.filter_by(job_id=job_id).order_by(JobInstruction.created_at).all()
    return jsonify([{
        "id": i.id, "content": i.content, "status": i.status, "stage_applied": i.stage_applied,
        "target_agents": i.target_agents, "orchestrator_note": i.orchestrator_note,
        "created_at": i.created_at.isoformat(), "applied_at": i.applied_at.isoformat() if i.applied_at else None,
    } for i in rows])


@bp.post("/<job_id>/assistant")
def ask_assistant(job_id):
    """Chat-driven, on-demand re-run of one of THIS job's own analysis agents against
    already-validated data -- e.g. "redo the risk score excluding the one-off item". This
    is deliberately separate from the fixed data->analysis->delivery pipeline sequence
    (unchanged -- see agents/*/supervisor.py) and from /api/qa (unchanged -- a pure lookup
    over existing facts/findings/report, never re-runs anything): this endpoint is for
    requests that need a specific agent to actually compute something fresh.

    Body: {"message": str, "auto": bool, "chosen_agent": str?, "action_note": str?}.
    - First call: send "message" only. If the orchestrator can't tell which agent you mean,
      the response is {"type": "clarification", "question", "options": [{label,
      description, agent}, ...]} -- Claude-Code-style multiple choice -- unless "auto" is
      true, in which case it just picks its best-ranked option itself instead of asking.
    - Follow-up call (after a clarification): send "chosen_agent" (from one of the
      options' `agent` values) and "action_note" (that option's intent) to actually run it.
    Either way, a run produces {"type": "answer", "answer", "agent_used", "status"} and
    shows up in GET /api/jobs/<id>/tasks like any other agent task, with any new metrics/
    findings visible via the usual /metrics and /findings endpoints.
    """
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    if not job.dataset_version_id:
        return jsonify(error="This job hasn't produced a validated dataset yet -- run the pipeline first."), 400

    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    auto = bool(data.get("auto"))
    chosen_agent = (data.get("chosen_agent") or "").strip()
    action_note = (data.get("action_note") or message).strip()

    if not message and not chosen_agent:
        return jsonify(error="message is required"), 400

    analysis_classes = {cls.name: cls for cls in modules_for(job.plan_template)}
    delivery_classes = {
        "insight_reasoner": InsightReasonerAgent,
        "report_writer": ReportWriterAgent,
        "chart_spec": ChartSpecAgent,
    }
    agent_classes = {**analysis_classes, **delivery_classes}

    # Analysis agents ordered first (preserves default test selection), followed by delivery agents
    agent_descriptions = {k: v for k, v in STAGE_AGENT_DESCRIPTIONS.get("analysis", {}).items() if k in analysis_classes}
    for k, v in STAGE_AGENT_DESCRIPTIONS.get("delivery", {}).items():
        if k in agent_classes and k not in agent_descriptions:
            agent_descriptions[k] = v

    llm = get_llm_gateway()

    if not chosen_agent:
        available_agents = [{"agent": name, "does": desc} for name, desc in agent_descriptions.items()]
        prompt = [
            {"role": "system", "content": prompts.ASSISTANT_ROUTER},
            {"role": "user", "content": embed_json("USER_MESSAGE_JSON", {"message": message}) + "\n"
                                         + embed_json("AVAILABLE_AGENTS_JSON", available_agents)},
        ]
        try:
            decision: AssistantDecision = llm.complete(prompt, schema=AssistantDecision, tier="reasoning")
        except Exception as exc:
            return jsonify(error=f"Could not interpret the request: {exc}"), 502

        if decision.needs_clarification and decision.options and not auto:
            return jsonify(type="clarification", question=decision.question,
                            options=[o.model_dump() for o in decision.options])

        chosen_agent = decision.chosen_agent or (decision.options[0].agent if decision.options else "")
        action_note = decision.action_note or message
        if not chosen_agent or chosen_agent not in agent_classes:
            return jsonify(type="answer", agent_used=None, status=None, answer=(
                "I couldn't match this to a specific analysis re-run -- try rephrasing, or "
                "ask a factual question about the existing results instead (that goes "
                "through /api/qa)."
            ))

    if chosen_agent not in agent_classes:
        return jsonify(error=f"'{chosen_agent}' isn't an active module for this job"), 400

    agent_cls = agent_classes[chosen_agent]
    insights_uri = f"{job.id}/delivery/insights.json"
    params = {"dataset_version_id": job.dataset_version_id, "user_guidance": action_note}
    if chosen_agent in ("report_writer", "chart_spec"):
        params["insights_uri"] = insights_uri

    spec = TaskSpec(
        task_id=new_id("t_"), job_id=job.id, tenant_id=job.tenant_id, agent=agent_cls.name,
        goal=f"chat-requested re-run: {action_note}",
        params=params,
    )
    # WorkerAgent.run() already records its own TaskRun (see agents/base.py), so this run
    # shows up in GET /api/jobs/<id>/tasks the same as any pipeline-triggered agent call --
    # no separate bookkeeping needed here.
    result = agent_cls(llm).run(spec)

    # If the report writer was re-run, verify the new draft and refresh the Report record
    if chosen_agent == "report_writer" and result.outputs:
        draft_uri = result.outputs[0].uri
        try:
            verifier_result = VerifierAgent(llm).run(TaskSpec(
                task_id=new_id("t_"), job_id=job.id, tenant_id=job.tenant_id, agent="verifier",
                goal=f"verify chat-updated report for job {job.id}",
                params={"dataset_version_id": job.dataset_version_id, "draft_uri": draft_uri, "insights_uri": insights_uri},
            ))
            resolved_sections = verifier_result.usage.get("resolved_sections") or []
            if not resolved_sections and draft_uri:
                fallback_draft = json.loads(storage.resolve(draft_uri).read_text())
                for s in fallback_draft.get("sections", []):
                    res_body, _ = resolve_placeholders(s["body"], job.dataset_version_id)
                    resolved_sections.append({**s, "body": res_body})
            charts_path = f"{job.id}/delivery/charts.json"
            charts = json.loads(storage.resolve(charts_path).read_text()) if storage.resolve(charts_path).exists() else []
            draft_title = json.loads(storage.resolve(draft_uri).read_text()).get("title", "Financial Analysis Report")
            html_res = render_html(job.id, draft_title, resolved_sections, charts)
            docx_uri = render_docx(job.id, draft_title, resolved_sections, charts)
            pdf_uri = render_pdf(job.id, html_res["html"])
            report = Report.query.filter_by(dataset_version=job.dataset_version_id).order_by(Report.created_at.desc()).first()
            if report is None:
                report = Report(id=new_id("rep_"), dataset_version=job.dataset_version_id, template=job.plan_template)
                db.session.add(report)
            report.draft_uri = draft_uri
            report.html_uri = html_res["html_uri"]
            report.docx_uri = docx_uri
            report.pdf_uri = pdf_uri
            report.verifier_status = "pass" if verifier_result.status.value == "done" else "failed"
            report.revision = (report.revision or 0) + 1
            db.session.commit()
        except Exception as exc:
            import traceback
            traceback.print_exc()

    resolved_summary, _ = resolve_placeholders(result.summary, job.dataset_version_id)
    return jsonify(type="answer", answer=resolved_summary, agent_used=chosen_agent, status=result.status.value)


def _get_scoped_job(job_id: str) -> Job | None:
    return Job.query.filter_by(id=job_id, tenant_id=current_tenant_id()).first()


def _job_dict(job: Job) -> dict:
    return {
        "id": job.id, "stage": job.stage, "status": job.status, "progress_pct": job.progress_pct,
        "progress_message": job.progress_message, "dataset_version_id": job.dataset_version_id,
        "error": job.error, "updated_at": job.updated_at.isoformat(),
    }
