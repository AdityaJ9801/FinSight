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
    return jsonify([{
        "id": i.id, "kind": i.kind, "payload": i.payload, "status": i.status, "created_at": i.created_at.isoformat(),
    } for i in items])


@bp.post("/items/<item_id>/resolve")
def resolve_item(item_id):
    item = ReviewItem.query.get(item_id)
    if item is None or _scoped_job(item.job_id) is None:
        return jsonify(error="not found"), 404
    if item.status == "resolved":
        return jsonify(error="already resolved"), 409

    resolution = request.get_json(force=True, silent=True) or {}
    tenant_id = current_tenant_id()

    if item.kind == "mapping":
        account_id = resolution.get("account_id")
        if not account_id:
            return jsonify(error="resolution.account_id is required for a mapping review item"), 400
        payload = item.payload
        doc = Document.query.get(payload["document_id"])
        write_memory(tenant_id, doc.entity_id if doc else None, doc.layout_id if doc else None,
                     payload["label"], account_id, confidence=1.0, method="human", approved_by=current_user_id())
        # Re-point facts already written under the low-confidence guess to the corrected
        # account. Simplification: this matches by (document, suggested_account_id), not by
        # the exact source row, so if two distinct unmapped labels in the same document both
        # fell back to the same default account, correcting one would also move the other's
        # facts. Acceptable for a single low-confidence label per document (the common case);
        # a precise fix would filter on FinancialFact.source_ref's row index too.
        FinancialFact.query.filter_by(source_doc=payload.get("document_id")).filter(
            FinancialFact.account_id == payload.get("suggested_account_id")
        ).update({"account_id": account_id, "confidence": 1.0})

    item.status = "resolved"
    item.resolution = resolution
    item.resolved_by = current_user_id()
    from datetime import datetime, timezone

    item.resolved_at = datetime.now(timezone.utc)
    db.session.commit()

    # Mirrors DataSupervisor.run_stage's own blocking-vs-gap distinction: a low-confidence
    # mapping item that never blocked the gate in the first place (AUTO_APPROVE_LOW_CONFIDENCE)
    # shouldn't be required reading before the job can resume -- otherwise a job with any
    # auto-approved mapping gaps (the common case) could never resume once ANY genuinely
    # blocking item (e.g. a reconciliation failure) got resolved, since those gap items are
    # still persisted with status="open" for visibility/audit but were never actually blocking.
    open_items = ReviewItem.query.filter_by(job_id=item.job_id, status="open").all()
    auto_approve_mappings = current_app.config.get("AUTO_APPROVE_LOW_CONFIDENCE", True)
    remaining = sum(1 for i in open_items if not (i.kind == "mapping" and auto_approve_mappings))
    if remaining == 0:
        from app.workers.tasks import run_data_stage

        job = Job.query.get(item.job_id)
        job.status = "MAPPING"
        db.session.commit()
        run_data_stage.delay(job.id)

    return jsonify(status="resolved", remaining_open=remaining)
