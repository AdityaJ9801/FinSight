from flask import Blueprint, current_app, jsonify, request

from app.api.deps import current_tenant_id, current_user_id
from app.extensions import db
from app.memory.mapping_memory import write_memory
from app.models.dataset import FinancialFact
from app.models.document import Document
from app.models.job import Job
from app.models.review import ReviewItem

bp = Blueprint("review", __name__)


def _scoped_job(job_id: str) -> Job | None:
    return Job.query.filter_by(id=job_id, tenant_id=current_tenant_id()).first()


@bp.get("/items")
def list_items():
    job_id = request.args.get("job_id")
    if not job_id or _scoped_job(job_id) is None:
        return jsonify(error="job_id is required and must belong to your tenant"), 400
    status = request.args.get("status", "open")
    items = ReviewItem.query.filter_by(job_id=job_id, status=status).all()

    # Dynamic synthesis: if job is in NEEDS_ANALYST, ensure a verification review item exists
    job = Job.query.get(job_id)
    if job and job.status == "NEEDS_ANALYST" and status == "open" and not any(i.kind == "verification" for i in items):
        from app.models.report import Report
        from app.utils.ids import new_id
        rep = Report.query.filter_by(dataset_version=job.dataset_version_id).order_by(Report.created_at.desc()).first() if job.dataset_version_id else None
        v_item = ReviewItem(
            id=new_id("rev_"),
            job_id=job.id,
            kind="verification",
            payload={
                "check_code": "VERIFIER_DISCREPANCY",
                "summary": "Report draft requires analyst verification sign-off",
                "issues": [job.progress_message or "Automated verifier flagged claims in draft report"],
                "explanation": "The draft report is compiled and available for review. An analyst can review the flagged claims, approve publication as verified, or supply manual audit notes.",
                "recommendation": {
                    "kind": "verification",
                    "action": "approve_and_publish",
                    "title": "Analyst Verification Sign-Off",
                    "confidence": 0.9,
                    "reasoning": "Report draft is generated and available. Approving removes the unverified warning and completes the analysis.",
                    "audit_note": "Analyst reviewed draft claims and certified report publication.",
                    "auto_resolvable": True,
                },
            },
        )
        db.session.add(v_item)
        db.session.commit()
        items.append(v_item)

    return jsonify([{
        "id": i.id, "kind": i.kind, "payload": i.payload, "status": i.status, "created_at": i.created_at.isoformat(),
    } for i in items])


@bp.post("/recommend")
def generate_recommendations():
    data = request.get_json(force=True, silent=True) or {}
    job_id = data.get("job_id") or request.args.get("job_id")
    if not job_id or _scoped_job(job_id) is None:
        return jsonify(error="job_id is required and must belong to your tenant"), 400

    from app.agents.base import TaskSpec
    from app.agents.data.verification_advisor import VerificationAdvisorAgent
    from app.llm_gateway import get_llm_gateway
    from app.utils.ids import new_id

    job = Job.query.get(job_id)
    advisor = VerificationAdvisorAgent(get_llm_gateway())
    spec = TaskSpec(
        task_id=new_id("t_"), job_id=job.id, tenant_id=job.tenant_id, agent="verification_advisor",
        goal="verification advice", params={"job_id": job.id, "auto_resolve": False},
    )
    res = advisor.run(spec)
    return jsonify(status="ok", summary=res.summary, usage=res.usage)


@bp.post("/auto-resolve")
def auto_resolve():
    data = request.get_json(force=True, silent=True) or {}
    job_id = data.get("job_id") or request.args.get("job_id")
    if not job_id or _scoped_job(job_id) is None:
        return jsonify(error="job_id is required and must belong to your tenant"), 400

    from app.agents.base import TaskSpec
    from app.agents.data.verification_advisor import VerificationAdvisorAgent
    from app.llm_gateway import get_llm_gateway
    from app.utils.ids import new_id

    job = Job.query.get(job_id)
    advisor = VerificationAdvisorAgent(get_llm_gateway())
    spec = TaskSpec(
        task_id=new_id("t_"), job_id=job.id, tenant_id=job.tenant_id, agent="verification_advisor",
        goal="verification auto resolve", params={"job_id": job.id, "auto_resolve": True},
    )
    res = advisor.run(spec)
    return jsonify(status="ok", summary=res.summary, usage=res.usage)



@bp.post("/items/<item_id>/resolve")
def resolve_item(item_id):
    item = ReviewItem.query.get(item_id)
    if item is None or _scoped_job(item.job_id) is None:
        return jsonify(error="not found"), 404
    if item.status == "resolved":
        return jsonify(error="already resolved"), 409

    resolution = request.get_json(force=True, silent=True) or {}
    tenant_id = current_tenant_id()
    rec = (item.payload or {}).get("recommendation") or {}

    if item.kind == "mapping":
        account_id = resolution.get("account_id") or rec.get("suggested_account_id")
        if not account_id:
            return jsonify(error="resolution.account_id is required for a mapping review item"), 400
        payload = item.payload
        doc = Document.query.get(payload["document_id"])
        write_memory(tenant_id, doc.entity_id if doc else None, doc.layout_id if doc else None,
                     payload["label"], account_id, confidence=1.0, method="human", approved_by=current_user_id())
        FinancialFact.query.filter_by(source_doc=payload.get("document_id")).filter(
            FinancialFact.account_id == payload.get("suggested_account_id")
        ).update({"account_id": account_id, "confidence": 1.0})
        resolution["account_id"] = account_id

    elif item.kind == "reconciliation":
        if not resolution.get("note"):
            resolution["note"] = rec.get("audit_note") or "Accepted by reviewer"

    elif item.kind == "verification":
        action = resolution.get("action", "approve")
        note = resolution.get("note") or rec.get("audit_note") or "Analyst verified and approved draft report."
        resolution["note"] = note
        resolution["action"] = action

        from app.models.report import Report
        from app.agents.delivery.publishing import publish_report, resolve_draft_sections
        from app.orchestrator import blackboard
        job = Job.query.get(item.job_id)
        if job and job.dataset_version_id:
            draft = blackboard.read(job.id, "draft") or {}
            sec = resolve_draft_sections(draft, job.dataset_version_id)
            report = Report.query.filter_by(dataset_version=job.dataset_version_id).order_by(Report.created_at.desc()).first()
            if report:
                publish_report(job, job.dataset_version_id, sec, verified=True, draft_uri=None, report=report)
                report.verifier_status = "passed"
            job.status = "COMPLETED"
            job.set_progress(100, "Report verified and ready")
            db.session.commit()

    item.status = "resolved"
    item.resolution = resolution
    item.resolved_by = current_user_id()
    from datetime import datetime, timezone

    item.resolved_at = datetime.now(timezone.utc)
    db.session.commit()

    open_items = ReviewItem.query.filter_by(job_id=item.job_id, status="open").all()
    auto_approve_mappings = current_app.config.get("AUTO_APPROVE_LOW_CONFIDENCE", True)
    remaining = sum(1 for i in open_items if not (i.kind == "mapping" and auto_approve_mappings))
    if remaining == 0:
        job = Job.query.get(item.job_id)
        if item.kind == "verification" or (job and job.status == "NEEDS_ANALYST"):
            if job:
                job.status = "COMPLETED"
                job.set_progress(100, "Report verified and ready")
                db.session.commit()
        else:
            from app.workers.tasks import run_data_stage
            if job:
                job.status = "MAPPING"
                db.session.commit()
                run_data_stage.delay(job.id)

    return jsonify(status="resolved", remaining_open=remaining)

