import hashlib
import json
import os
import time

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from werkzeug.utils import secure_filename

from app.agents.base import TaskSpec
from app.agents.schemas import AssistantDecision
from app.api.deps import current_tenant_id, current_user_id
from app.domain.benchmarks import load_benchmarks
from app.domain.chat_intent import is_action_request
from app.extensions import db
from app.llm_gateway import get_llm_gateway, prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.audit import AuditLog, log_action
from app.models.bank import BankTransaction
from app.models.dataset import DatasetVersion, FinancialFact
from app.models.document import Document
from app.models.finding import Finding
from app.models.gst import GstReturn
from app.models.job import Job, JobInstruction, JobProfile, TaskRun
from app.models.metric import Metric
from app.models.report import Report
from app.models.review import ReviewItem
from app.models.validation import ValidationResult
from app.agents import registry as agent_registry
from app.agents.delivery.publishing import publish_report, resolve_draft_sections
from app.agents.verifier import VerifierAgent
from app.orchestrator import blackboard
from app.orchestrator.orchestrator import QueueUnavailableError, create_job, start
from app.orchestrator.templates import module_names_for
from app.tools.report_render import resolve_placeholders
from app.utils import storage
from app.utils.ids import new_id

bp = Blueprint("jobs", __name__)


_UPLOAD_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf"}
# Statuses in which a job can take more statements: not while stages are executing.
_SETTLED_STATUSES = {"COMPLETED", "FAILED", "AWAITING_REVIEW", "NEEDS_ANALYST", "PARTIAL"}


def _store_uploads(job: Job, files, tenant_id: str, entity_id: str | None) -> tuple[list[str], list[str]]:
    """Writes uploaded files as this job's Documents. Returns (added, skipped) filenames;
    a file whose content is already part of this job is skipped rather than double-counted."""
    in_job = {d.sha256 for d in Document.query.filter_by(job_id=job.id).all()}
    added, skipped = [], []
    for file_storage in files:
        filename = secure_filename(file_storage.filename or "")
        if not filename:
            continue
        content = file_storage.read()
        sha256 = hashlib.sha256(content).hexdigest()
        if sha256 in in_job:
            skipped.append(filename)
            continue
        in_job.add(sha256)
        existing = Document.query.filter_by(tenant_id=tenant_id, sha256=sha256).first()
        uri = storage.write_bytes(f"{job.id}/raw/{new_id()}_{filename}", content)
        db.session.add(Document(
            id=new_id("doc_"), tenant_id=tenant_id, entity_id=entity_id, job_id=job.id,
            file_uri=uri, original_filename=filename, sha256=sha256,
            mime=file_storage.mimetype, duplicate_of=existing.id if existing else None,
            status="uploaded",
        ))
        added.append(filename)
    return added, skipped


def _unsupported(files) -> list[str]:
    return [f.filename for f in files
            if f.filename and os.path.splitext(f.filename)[1].lower() not in _UPLOAD_EXTENSIONS]


def _save_profile(job_id: str, company_name: str | None, industry: str | None) -> str | None:
    """Upserts the job's company/industry. Returns an error message for an unknown industry."""
    if industry and industry not in load_benchmarks()["industries"]:
        return f"unknown industry '{industry}'"
    profile = db.session.get(JobProfile, job_id) or JobProfile(job_id=job_id)
    if company_name is not None:
        profile.company_name = company_name.strip()[:255] or None
    if industry is not None:
        profile.industry = industry or None
    db.session.add(profile)
    return None


@bp.post("")
def create_and_start_job():
    tenant_id = current_tenant_id()
    goal = request.form.get("goal", "Full financial analysis")
    plan_template = request.form.get("plan_template", "full_analysis")
    entity_id = request.form.get("entity_id")
    files = request.files.getlist("files")

    if not files:
        return jsonify(error="at least one file is required (multipart field 'files')"), 400
    bad = _unsupported(files)
    if bad:
        return jsonify(error=f"unsupported file type: {', '.join(bad)} (use CSV, Excel or PDF)"), 400
    industry = request.form.get("industry")
    if industry and industry not in load_benchmarks()["industries"]:
        return jsonify(error=f"unknown industry '{industry}'"), 400

    job = create_job(tenant_id, entity_id, current_user_id(), goal, plan_template)
    _save_profile(job.id, request.form.get("company_name"), industry)
    _store_uploads(job, files, tenant_id, entity_id)
    db.session.commit()

    try:
        start(job)
    except QueueUnavailableError as exc:
        return jsonify(job_id=job.id, status=job.status, error=str(exc)), 503
    return jsonify(job_id=job.id, status=job.status), 201


@bp.post("/<job_id>/documents")
def add_documents(job_id):
    """Adds statements to an existing analysis and re-runs it on everything uploaded so far.

    The re-run writes into a NEW dataset version (parent_version = the previous one) rather
    than mutating the old one, so earlier figures stay intact and auditable; the job's
    dataset_version_id pointer moves to the new version. Review items raised against the
    previous version are marked "superseded": they described data that is about to be
    re-extracted, and a stale "accepted" reconciliation must not auto-accept the same check
    against the new data."""
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    if job.status not in _SETTLED_STATUSES:
        return jsonify(error="this analysis is still running; add statements once it finishes"), 409
    files = request.files.getlist("files")
    if not files:
        return jsonify(error="at least one file is required (multipart field 'files')"), 400
    bad = _unsupported(files)
    if bad:
        return jsonify(error=f"unsupported file type: {', '.join(bad)} (use CSV, Excel or PDF)"), 400

    added, skipped = _store_uploads(job, files, job.tenant_id, job.entity_id)
    if not added:
        db.session.rollback()
        return jsonify(error="these files are already part of this analysis", skipped=skipped), 400

    previous = job.dataset_version_id
    version = DatasetVersion(id=new_id("dsv_"), entity_id=job.entity_id, job_id=job.id, status="DRAFT",
                             parent_version=previous)
    db.session.add(version)
    job.dataset_version_id = version.id
    # Every document is re-read into the new version, not just the new ones: facts are
    # scoped to a dataset version, and reconciliation must see the whole set together.
    Document.query.filter_by(job_id=job.id).update({"status": "uploaded"})
    ReviewItem.query.filter(ReviewItem.job_id == job.id, ReviewItem.status != "superseded").update(
        {"status": "superseded"}, synchronize_session=False)
    job.stage, job.status, job.error, job.replans = "data", "CREATED", None, 0
    job.set_progress(0, f"Added {len(added)} statement(s); re-running the analysis")
    db.session.commit()
    log_action("documents_added", tenant_id=job.tenant_id, job_id=job.id, added=added,
               previous_dataset_version=previous, dataset_version=version.id)

    try:
        start(job)
    except QueueUnavailableError as exc:
        return jsonify(job_id=job.id, status=job.status, added=added, skipped=skipped, error=str(exc)), 503
    return jsonify(job_id=job.id, status=job.status, added=added, skipped=skipped), 202


@bp.put("/<job_id>/profile")
def update_profile(job_id):
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    data = request.get_json(force=True, silent=True) or {}
    err = _save_profile(job.id, data.get("company_name"), data.get("industry"))
    if err:
        db.session.rollback()
        return jsonify(error=err), 400
    db.session.commit()
    return jsonify(_job_dict(job))


@bp.get("")
def list_jobs():
    """All of this tenant's jobs, newest first -- so any browser sees the full history,
    not just the jobs it happened to create."""
    limit = min(request.args.get("limit", 100, type=int), 500)
    jobs = (Job.query.filter_by(tenant_id=current_tenant_id())
            .order_by(Job.created_at.desc()).limit(limit).all())
    ids = [j.id for j in jobs]
    doc_counts = dict(
        db.session.query(Document.job_id, db.func.count(Document.id))
        .filter(Document.job_id.in_(ids)).group_by(Document.job_id).all()
    ) if jobs else {}
    profiles = {p.job_id: p for p in JobProfile.query.filter(JobProfile.job_id.in_(ids)).all()} if jobs else {}
    return jsonify([{**_job_dict(j, profiles.get(j.id)), "document_count": doc_counts.get(j.id, 0)} for j in jobs])


@bp.get("/<job_id>")
def get_job(job_id):
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404
    docs = Document.query.filter_by(job_id=job_id).order_by(Document.created_at).all()
    versions = DatasetVersion.query.filter_by(job_id=job_id).count()
    current = db.session.get(DatasetVersion, job.dataset_version_id) if job.dataset_version_id else None
    return jsonify({**_job_dict(job), "dataset_versions": versions,
                    # When the current run began: the task trace keeps earlier versions' runs
                    # for audit, and the UI uses this to show only the current run's progress.
                    "run_started_at": current.created_at.isoformat() if current and current.created_at else None,
                    "documents": [{
        "id": d.id, "filename": d.original_filename, "doc_type": d.doc_type, "status": d.status,
        "period_end": d.period_end.isoformat() if d.period_end else None,
    } for d in docs]})


@bp.delete("/<job_id>")
def delete_job(job_id):
    """Deletes a job and everything scoped to it -- every dataset version's facts, metrics,
    findings and reports, plus documents, review items, instructions, the task trace, and its
    on-disk file tree. A currently-running job can be deleted too: the Celery task chain
    already no-ops cleanly on a missing job (see run_data_stage/run_analysis_stage/
    run_delivery_stage's `if job is None: return`), so this just lets the in-flight task
    finish and discard its result rather than trying to cancel it -- simpler and safer than
    interrupting a worker mid-task."""
    job = _get_scoped_job(job_id)
    if job is None:
        return jsonify(error="not found"), 404

    # Newest first: each version's parent_version FK points at the one before it.
    versions = [v.id for v in DatasetVersion.query.filter_by(job_id=job_id)
                .order_by(DatasetVersion.created_at.desc()).all()]
    for model in (FinancialFact, BankTransaction, GstReturn, ValidationResult, Metric, Finding, Report):
        model.query.filter(model.dataset_version.in_(versions)).delete(synchronize_session=False)
    for version_id in versions:
        DatasetVersion.query.filter_by(id=version_id).delete()

    ReviewItem.query.filter_by(job_id=job_id).delete()
    TaskRun.query.filter_by(job_id=job_id).delete()
    JobInstruction.query.filter_by(job_id=job_id).delete()
    JobProfile.query.filter_by(job_id=job_id).delete()
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

    # Re-runnable agents come from the agent registry: this job's active analysis modules
    # first (plan-template order), then the delivery agents that can be re-run on demand.
    active_modules = set(module_names_for(job.plan_template))
    candidates = [a for a in agent_registry.rerunnable("analysis") if a.name in active_modules]
    candidates += agent_registry.rerunnable("delivery")
    agent_classes = {a.name: a.load() for a in candidates}
    agent_descriptions = {a.name: a.description for a in candidates}

    llm = get_llm_gateway()

    # "force" is set by the UI when the QA router itself judged the message to be an action
    # request -- a second opinion that catches phrasings the deterministic gate doesn't know.
    if not chosen_agent and not data.get("force") and not is_action_request(message):
        # A question about existing results, not a recompute request: hand back to the
        # caller to answer it through /api/qa instead of re-running an agent.
        return jsonify(type="answer", agent_used=None, status=None, route="question", answer="")

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
    insights_uri = blackboard.uri(job.id, "insights")
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

    # Agents whose output feeds the rendered report: re-verify (for a new draft) and
    # re-render through the same publish path the pipeline uses, so the report reflects
    # the re-run instead of silently going stale.
    if chosen_agent in ("report_writer", "chart_spec", "detailed_analytics") and result.outputs:
        try:
            _refresh_report(job, llm, new_draft_uri=result.outputs[0].uri if chosen_agent == "report_writer" else None)
        except Exception:  # noqa: BLE001 -- the re-run itself succeeded; report refresh is best-effort
            current_app.logger.exception("report refresh after chat re-run failed")

    resolved_summary, _ = resolve_placeholders(result.summary, job.dataset_version_id)
    return jsonify(type="answer", answer=resolved_summary, agent_used=chosen_agent, status=result.status.value)


def _refresh_report(job: Job, llm, new_draft_uri: str | None) -> None:
    report = Report.query.filter_by(dataset_version=job.dataset_version_id).order_by(Report.created_at.desc()).first()
    draft_uri = new_draft_uri or (report.draft_uri if report else None)
    if draft_uri is None:
        return
    verifier_result = VerifierAgent(llm).run(TaskSpec(
        task_id=new_id("t_"), job_id=job.id, tenant_id=job.tenant_id, agent="verifier",
        goal=f"verify chat-updated report for job {job.id}",
        params={"dataset_version_id": job.dataset_version_id, "draft_uri": draft_uri,
                "insights_uri": blackboard.uri(job.id, "insights")},
    ))
    verified = verifier_result.status.value == "done"
    sections = verifier_result.usage.get("resolved_sections") or \
        resolve_draft_sections(blackboard.read(job.id, "draft") or {}, job.dataset_version_id)
    report = publish_report(job, job.dataset_version_id, sections, verified=verified, draft_uri=draft_uri, report=report)
    report.revision = (report.revision or 0) + 1
    db.session.commit()


def _get_scoped_job(job_id: str) -> Job | None:
    return Job.query.filter_by(id=job_id, tenant_id=current_tenant_id()).first()


def _job_dict(job: Job, profile: JobProfile | None = None) -> dict:
    if profile is None:
        profile = db.session.get(JobProfile, job.id)
    return {
        "company_name": profile.company_name if profile else None,
        "industry": profile.industry if profile else None,
        "id": job.id, "stage": job.stage, "status": job.status, "progress_pct": job.progress_pct,
        "progress_message": job.progress_message, "dataset_version_id": job.dataset_version_id,
        "error": job.error, "updated_at": job.updated_at.isoformat(),
        "goal": job.goal, "plan_template": job.plan_template,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
