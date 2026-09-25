"""Data-stage supervisor: fans out intake -> extract -> map per document (ThreadPoolExecutor
stands in for the design doc's cross-process fan-out, per the plan's scoping decision),
then runs reconciliation once across the whole dataset version and decides the stage gate.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask

from app.agents.base import AgentResult, Status, TaskSpec
from app.agents.data.extractor import ExtractorAgent
from app.agents.data.intake import IntakeAgent
from app.agents.data.mapper import SchemaMapperAgent
from app.agents.data.reconciler import ReconcilerAgent
from app.domain.validation_rules import within_materiality
from app.extensions import db
from app.models.dataset import FinancialFact
from app.models.document import Document
from app.models.review import ReviewItem
from app.utils.ids import new_id

# doc types with a raw-table -> canonical-CoA mapping step; bank/GST write facts directly.
_NEEDS_MAPPING = {"balance_sheet", "pnl", "trial_balance", "other", "ageing_ar", "ageing_ap", "loan_schedule", "inventory"}
# Statuses that mean "this document's work for the data stage is already done" -- checked
# on resume (e.g. after a human review correction) so we don't redo intake/extract/map,
# only reconciliation, which is what the correction actually needs re-run (§6.10 resumability).
_DONE_STATUSES = {"mapped", "extracted"}


def _make_spec(job, agent_name: str, params: dict) -> TaskSpec:
    return TaskSpec(task_id=new_id("t_"), job_id=job.id, tenant_id=job.tenant_id, agent=agent_name,
                     goal=f"{agent_name} for job {job.id}", params=params)


def _process_document(app: Flask, llm, job_id: str, document_id: str, dataset_version_id: str,
                       mapper_guidance: str | None = None) -> dict:
    """Runs intake -> extract -> map for one document. Executed in a worker thread, so it
    needs its own Flask app context (SQLAlchemy sessions aren't thread-safe to share)."""
    with app.app_context():
        from app.models.job import Job

        try:
            job = Job.query.get(job_id)
            doc = Document.query.get(document_id)
            if doc.status in _DONE_STATUSES:
                already_done = AgentResult(task_id=new_id("t_"), status=Status.DONE,
                                            summary=f"'{doc.original_filename}' already processed; skipped on resume.")
                return {"document_id": document_id, "intake": already_done, "extract": already_done, "map": []}

            intake_result: AgentResult = IntakeAgent(llm).run(_make_spec(job, "intake_classifier", {"document_id": document_id}))
            if intake_result.status == Status.FAILED:
                return {"document_id": document_id, "intake": intake_result, "extract": None, "map": []}

            extract_result: AgentResult = ExtractorAgent(llm).run(
                _make_spec(job, "extractor", {"document_id": document_id, "dataset_version_id": dataset_version_id})
            )
            doc = Document.query.get(document_id)
            # One mapper run per extracted table -- a workbook with several sheets (or a
            # PDF with several tables) yields one output artifact per sheet/table, each
            # needing its own row-label -> canonical-account mapping.
            map_results: list[AgentResult] = []
            if extract_result.status == Status.DONE and doc.doc_type in _NEEDS_MAPPING:
                for artifact in extract_result.outputs:
                    table_name = artifact.id.split(":", 1)[1] if ":" in artifact.id else None
                    map_results.append(SchemaMapperAgent(llm).run(_make_spec(
                        job, "schema_mapper",
                        {"document_id": document_id, "dataset_version_id": dataset_version_id,
                         "raw_table_uri": artifact.uri, "table_name": table_name,
                         "user_guidance": mapper_guidance},
                    )))
            return {"document_id": document_id, "intake": intake_result, "extract": extract_result, "map": map_results}
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Unexpected error processing document %s: %s", document_id, exc)
            failed = AgentResult(task_id=new_id("t_"), status=Status.FAILED,
                                  summary=f"Unexpected error processing document {document_id}: {exc}")
            return {"document_id": document_id, "intake": failed, "extract": failed, "map": []}


class DataSupervisor:
    name = "data_supervisor"

    def __init__(self, app: Flask, llm):
        self.app = app
        self.llm = llm

    def run_stage(self, job, dataset_version_id: str, guidance: dict[str, str] | None = None) -> bool:
        """Returns True if the stage gate passed (dataset VALIDATED[_WITH_GAPS]).
        guidance: {agent_name: note} from orchestrator.apply_pending_instructions -- only
        "schema_mapper" is meaningful here (see STAGE_AGENT_DESCRIPTIONS)."""
        documents = Document.query.filter_by(job_id=job.id).all()
        job.set_progress(10, f"Processing {len(documents)} document(s)")
        db.session.commit()
        mapper_guidance = (guidance or {}).get("schema_mapper")

        results = []
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(documents)))) as pool:
            futures = [
                pool.submit(_process_document, self.app, self.llm, job.id, doc.id, dataset_version_id, mapper_guidance)
                for doc in documents
            ]
            for future in as_completed(futures):
                results.append(future.result())

        review_items: list[ReviewItem] = []
        any_gap = False

        for r in results:
            if r["extract"] is None or r["extract"].status == Status.FAILED:
                any_gap = True
                continue
            if r["extract"].status == Status.PARTIAL:
                any_gap = True
            for map_result in (r["map"] or []):
                for lc in map_result.usage.get("low_confidence_mappings", []):
                    review_items.append(ReviewItem(id=new_id("rev_"), job_id=job.id, kind="mapping", payload=lc))

        job.set_progress(60, "Running reconciliation checks")
        db.session.commit()

        # Reconciliation review items an analyst already acknowledged shouldn't re-block the
        # gate on resume just because the same deterministic check still fails (§6 "Fail
        # loudly, degrade gracefully") -- they contribute a gap instead.
        accepted_checks = {
            ri.payload.get("check_code")
            for ri in ReviewItem.query.filter_by(job_id=job.id, kind="reconciliation", status="resolved").all()
        }

        recon_result = ReconcilerAgent(self.llm).run(_make_spec(job, "reconciler", {"dataset_version_id": dataset_version_id}))
        for failed in recon_result.usage.get("failed_checks", []):
            if failed["check_code"] in accepted_checks:
                any_gap = True
                continue
            review_items.append(ReviewItem(
                id=new_id("rev_"), job_id=job.id, kind="reconciliation",
                payload={"check_code": failed["check_code"], "expected": failed.get("expected"),
                         "actual": failed.get("actual"), "diff": failed.get("diff"),
                         "explanation": failed.get("explanation")},
            ))

        # An empty dataset must never silently "validate" -- with zero facts,
        # run_statement_checks() iterates nothing and every check trivially reports no
        # failures (caught against a live model whose intake classifier produced doc_type
        # values the mapper's _NEEDS_MAPPING set didn't recognize, so no document ever
        # reached the mapper at all). Treat it the same as a reconciliation failure.
        fact_count = FinancialFact.query.filter_by(dataset_version=dataset_version_id).count()
        if fact_count == 0 and not any(ri.kind == "reconciliation" and ri.payload.get("check_code") == "NO_FACTS"
                                        for ri in review_items):
            review_items.append(ReviewItem(
                id=new_id("rev_"), job_id=job.id, kind="reconciliation",
                payload={"check_code": "NO_FACTS", "expected": None, "actual": 0, "diff": None,
                         "explanation": "No financial facts were extracted from any document -- check that "
                                        "document classification and mapping produced usable data."},
            ))

        # Distinguish hard reconciliation blockers (e.g. NO_FACTS or check failures)
        # from informational low-confidence mapping gaps.
        auto_approve_mappings = self.app.config.get("AUTO_APPROVE_LOW_CONFIDENCE", True)
        materiality_pct = self.app.config.get("RECONCILIATION_MATERIALITY_PCT", 0.15)
        blocking_items: list[ReviewItem] = []

        for item in review_items:
            db.session.add(item)
            if item.kind == "mapping" and auto_approve_mappings:
                any_gap = True
            elif item.kind == "reconciliation" and within_materiality(item.payload, materiality_pct):
                any_gap = True
            else:
                blocking_items.append(item)

        if blocking_items:
            job.status = "AWAITING_REVIEW"
            job.set_progress(65, f"{len(blocking_items)} item(s) need analyst review")
            db.session.commit()
            return False

        from app.models.dataset import DatasetVersion

        dataset_version = DatasetVersion.query.get(dataset_version_id)
        dataset_version.status = "VALIDATED_WITH_GAPS" if any_gap else "VALIDATED"
        job.status = "DATA_VALIDATED"
        job.set_progress(70, "Dataset validated")
        db.session.commit()
        return True
