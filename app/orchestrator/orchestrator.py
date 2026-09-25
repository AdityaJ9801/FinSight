"""Orchestrator: interprets the job goal into a plan template, creates the Job + first
DatasetVersion row, and kicks off the Celery stage chain (design doc §4.4). Replanning
(§4.4 step 7) is capped at MAX_REPLANS to avoid retry loops on a persistently failing job.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app

from app.agents.schemas import InstructionInterpretation
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.dataset import DatasetVersion
from app.models.job import Job, JobInstruction, TaskRun
from app.orchestrator.templates import is_valid_template
from app.utils.ids import new_id

# What each stage's agents actually do, for the orchestrator to match a user's mid-run
# instruction against -- kept here (not derived from the agent classes themselves) since
# it's a plain-language description for an LLM prompt, not code the agents need to see.
STAGE_AGENT_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "data": {
        "schema_mapper": "maps raw financial-statement row labels to canonical chart-of-accounts ids",
    },
    "analysis": {
        "ratio": "computes profitability/liquidity/leverage/efficiency ratios and writes trend findings",
        "cash_wc": "computes cash flow and working capital metrics and findings",
        "forecast": "projects future revenue/PAT and writes forecast findings",
        "risk": "flags anomalies/red flags and computes the overall risk score",
        "gst": "reconciles GST returns against the ledger",
    },
    "delivery": {
        "insight_reasoner": "synthesizes findings across all analysis modules into ranked insights and computes health score",
        "report_writer": "drafts the executive financial analysis report and narrative",
        "chart_spec": "selects and renders financial trend charts and cost structure visualizations",
    },
}


class QueueUnavailableError(Exception):
    """Raised when the Celery broker (Redis) can't be reached, so the API can return a
    clear error instead of the request hanging or a raw connection traceback."""


def create_job(tenant_id: str, entity_id: str | None, created_by: str, goal: str, plan_template: str = "full_analysis") -> Job:
    if not is_valid_template(plan_template):
        plan_template = "full_analysis"

    job = Job(id=new_id("job_"), tenant_id=tenant_id, entity_id=entity_id, created_by=created_by,
              goal=goal, plan_template=plan_template, stage="data", status="CREATED")
    db.session.add(job)
    db.session.flush()

    dataset_version = DatasetVersion(id=new_id("dsv_"), entity_id=entity_id, job_id=job.id, status="DRAFT")
    db.session.add(dataset_version)
    job.dataset_version_id = dataset_version.id
    db.session.commit()
    return job


def start(job: Job) -> None:
    from kombu.exceptions import OperationalError

    from app.workers.tasks import run_data_stage

    job.status = "INGESTING"
    job.set_progress(5, "Job queued")
    db.session.commit()
    try:
        run_data_stage.delay(job.id)
    except OperationalError as exc:
        job.status = "FAILED"
        job.error = f"Could not reach the job queue (Redis): {exc}"
        db.session.commit()
        raise QueueUnavailableError(job.error) from exc


def replan(job: Job, reason: str | None = None) -> bool:
    """Returns True if a retry of the job's current stage was queued, False if the replan
    budget is exhausted (in which case the job is marked FAILED with `reason` preserved)."""
    max_replans = current_app.config["MAX_REPLANS"]
    if job.replans >= max_replans:
        job.status = "FAILED"
        job.error = f"Exceeded max replans ({max_replans}); last error: {reason}" if reason else \
            f"Exceeded max replans ({max_replans})"
        db.session.commit()
        return False

    job.replans += 1
    job.error = reason
    db.session.commit()

    from app.workers.tasks import run_analysis_stage, run_data_stage, run_delivery_stage

    stage_task = {"data": run_data_stage, "analysis": run_analysis_stage, "delivery": run_delivery_stage}.get(job.stage)
    if stage_task is None:
        return False
    stage_task.delay(job.id)
    return True


def apply_pending_instructions(job: Job, llm, stage: str) -> dict[str, str]:
    """Checks for user-provided mid-run guidance (JobInstruction rows, from
    POST /api/jobs/<id>/instructions) and, if any is relevant to the stage about to run,
    has the orchestrator -- an LLM call, not a keyword match -- decide which of THAT
    stage's specific agents it applies to and what to tell them. Returns
    {agent_name: guidance_note}; each targeted agent reads its own entry out of
    spec.params["user_guidance"] in its execute() (e.g. RatioTrendAgent via
    AnalysisModuleAgent.generate_findings). This is the actual "agent talks to agent"
    mechanism here -- per the design doc's JobState-as-blackboard pattern (§4.3), agents
    don't message each other directly; they coordinate through state the orchestrator
    writes and they read, same as everything else in this pipeline.

    Zero-cost when nothing is pending (the common case for every job that never uses this
    feature) -- no LLM call, no DB write, existing jobs behave exactly as before.
    """
    pending = JobInstruction.query.filter_by(job_id=job.id, status="pending").all()
    if not pending:
        return {}

    agent_descriptions = dict(STAGE_AGENT_DESCRIPTIONS.get(stage, {}))
    if stage == "analysis":
        from app.orchestrator.templates import modules_for

        active_names = {cls.name for cls in modules_for(job.plan_template)}
        agent_descriptions = {k: v for k, v in agent_descriptions.items() if k in active_names}
    if not agent_descriptions:
        return {}

    available_agents = [{"agent": name, "does": desc} for name, desc in agent_descriptions.items()]
    guidance_by_agent: dict[str, list[str]] = {}

    for instruction in pending:
        prompt = [
            {"role": "system", "content": prompts.ORCHESTRATOR_INSTRUCTION},
            {"role": "user", "content": embed_json("USER_INSTRUCTION_JSON", {"content": instruction.content}) + "\n"
                                         + embed_json("STAGE_JSON", {"stage": stage}) + "\n"
                                         + embed_json("AVAILABLE_AGENTS_JSON", available_agents)},
        ]
        try:
            decision: InstructionInterpretation = llm.complete(prompt, schema=InstructionInterpretation, tier="reasoning")
        except Exception:
            continue  # leave it pending -- the next stage boundary gets another chance

        if not decision.applies_now:
            continue
        valid_targets = [a for a in decision.target_agents if a in agent_descriptions]
        if not valid_targets:
            continue

        instruction.status = "applied"
        instruction.stage_applied = stage
        instruction.target_agents = valid_targets
        instruction.orchestrator_note = decision.guidance_note
        instruction.applied_at = datetime.now(timezone.utc)
        for agent_name in valid_targets:
            guidance_by_agent.setdefault(agent_name, []).append(decision.guidance_note)

        # Visible in the same live task-trace stream the frontend already renders (GET
        # /api/jobs/<id>/tasks), so the hand-off from orchestrator to agent is something a
        # user can actually see happening, not just a silent side effect.
        db.session.add(TaskRun(
            job_id=job.id, task_key=new_id("instr_apply_"), agent="orchestrator", status="done",
            confidence=1.0,
            summary=f"Incorporated your note into the {stage} stage for "
                    f"{', '.join(valid_targets)}: {decision.guidance_note}",
        ))

    db.session.commit()
    return {agent: " ".join(notes) for agent, notes in guidance_by_agent.items()}
