"""Celery task chain: one task per pipeline stage, chained by each task enqueueing the
next on success (design doc's DAG, simplified per the plan to stage-level Celery tasks
with in-task thread-pool fan-out). Each task is safe to re-enqueue -- see the per-document
resumability check in agents/data/supervisor.py and the AWAITING_REVIEW short-circuit here.
"""
from __future__ import annotations

from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.audit import log_action
from app.models.job import Job
from app.orchestrator.orchestrator import apply_pending_instructions, replan
from app.workers.celery_app import celery, flask_app


def _get_job(job_id: str) -> Job | None:
    # Ends any transaction left open on this (pooled, reused-across-tasks) connection
    # before reading -- without this, a task re-enqueued by a DIFFERENT process (the Flask
    # API's POST /review/items/<id>/resolve, after it commits job.status = "MAPPING" and
    # dispatches this task) can still see the pre-commit snapshot here, same class of bug
    # documented on jobs.py's stream_job SSE generator. Confirmed live: without this,
    # run_data_stage's AWAITING_REVIEW guard immediately below kept firing on the resumed
    # task (completing in ~0.03s, having done no real work), so "Accept & resume" appeared
    # to loop back to the same review prompt instead of actually re-running reconciliation.
    db.session.commit()
    return db.session.get(Job, job_id)


@celery.task(name="run_data_stage", bind=True, max_retries=1)
def run_data_stage(self, job_id: str):
    from app.agents.data.supervisor import DataSupervisor

    job = _get_job(job_id)
    if job is None:
        return
    if job.status == "AWAITING_REVIEW":
        # Guard against a stray re-enqueue while review items are still open (the resolve
        # endpoint is the only thing allowed to move a job out of AWAITING_REVIEW).
        return

    try:
        job.status = "MAPPING"
        db.session.commit()
        llm = get_llm_gateway()
        guidance = apply_pending_instructions(job, llm, stage="data")
        supervisor = DataSupervisor(flask_app, llm)
        passed = supervisor.run_stage(job, job.dataset_version_id, guidance=guidance)
        log_action("data_stage_complete", tenant_id=job.tenant_id, job_id=job.id, passed=passed)
        if passed:
            run_analysis_stage.delay(job_id)
    except Exception as exc:
        log_action("data_stage_error", tenant_id=job.tenant_id, job_id=job.id, error=str(exc), attempt=job.replans + 1)
        replan(job, reason=f"data stage error: {exc}")


@celery.task(name="run_analysis_stage", bind=True, max_retries=1)
def run_analysis_stage(self, job_id: str):
    from app.agents.analysis.supervisor import AnalysisSupervisor

    job = _get_job(job_id)
    if job is None:
        return
    try:
        job.stage = "analysis"
        job.status = "ANALYZING"
        db.session.commit()
        llm = get_llm_gateway()
        guidance = apply_pending_instructions(job, llm, stage="analysis")
        supervisor = AnalysisSupervisor(flask_app, llm)
        passed = supervisor.run_stage(job, job.dataset_version_id, guidance=guidance)
        log_action("analysis_stage_complete", tenant_id=job.tenant_id, job_id=job.id, passed=passed)
        if passed:
            run_delivery_stage.delay(job_id)
        else:
            job.status = "FAILED"
            job.error = "No analysis module produced usable output"
            db.session.commit()
    except Exception as exc:
        log_action("analysis_stage_error", tenant_id=job.tenant_id, job_id=job.id, error=str(exc), attempt=job.replans + 1)
        replan(job, reason=f"analysis stage error: {exc}")


@celery.task(name="run_delivery_stage", bind=True, max_retries=1)
def run_delivery_stage(self, job_id: str):
    from app.agents.delivery.supervisor import DeliverySupervisor

    job = _get_job(job_id)
    if job is None:
        return
    try:
        job.stage = "delivery"
        job.status = "RENDERING"
        db.session.commit()
        llm = get_llm_gateway()
        guidance = apply_pending_instructions(job, llm, stage="delivery")
        supervisor = DeliverySupervisor(flask_app, llm)
        passed = supervisor.run_stage(job, job.dataset_version_id, guidance=guidance)
        log_action("delivery_stage_complete", tenant_id=job.tenant_id, job_id=job.id, passed=passed)
    except Exception as exc:
        log_action("delivery_stage_error", tenant_id=job.tenant_id, job_id=job.id, error=str(exc), attempt=job.replans + 1)
        replan(job, reason=f"delivery stage error: {exc}")
