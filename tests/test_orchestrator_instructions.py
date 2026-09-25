"""apply_pending_instructions is the mechanism behind "talk to the pipeline while it's
running" (POST /api/jobs/<id>/instructions): the orchestrator decides, per stage boundary,
whether a user's note is relevant to that stage's specific agents and relays it into their
TaskSpec.params if so. Tested against the fake LLM backend (see fake_client._interpret_
instruction), which deterministically applies to every agent it's offered.
"""
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.job import JobInstruction, TaskRun
from app.models.tenant import Entity, Tenant
from app.orchestrator.orchestrator import apply_pending_instructions
from app.orchestrator.orchestrator import create_job
from app.utils.ids import new_id


def _make_job(app, plan_template="full_analysis"):
    tenant = Tenant(id=new_id("ten_"), name="Test Tenant")
    db.session.add(tenant)
    db.session.flush()
    entity = Entity(id=new_id("ent_"), tenant_id=tenant.id, legal_name="Test Co")
    db.session.add(entity)
    db.session.commit()
    return create_job(tenant.id, entity.id, created_by="tester", goal="test", plan_template=plan_template)


def test_no_pending_instructions_is_a_zero_cost_noop(app):
    with app.app_context():
        job = _make_job(app)
        llm = get_llm_gateway()

        guidance = apply_pending_instructions(job, llm, stage="analysis")

        assert guidance == {}
        assert TaskRun.query.filter_by(job_id=job.id, agent="orchestrator").count() == 0


def test_pending_instruction_gets_applied_to_analysis_stage_agents(app):
    with app.app_context():
        job = _make_job(app, plan_template="full_analysis")
        llm = get_llm_gateway()

        instruction = JobInstruction(id=new_id("instr_"), job_id=job.id,
                                      content="Treat the large one-off legal settlement as non-recurring.")
        db.session.add(instruction)
        db.session.commit()

        guidance = apply_pending_instructions(job, llm, stage="analysis")

        # full_analysis runs all 5 analysis modules; the fake backend applies to all of them.
        assert set(guidance.keys()) == {"ratio", "cash_wc", "forecast", "risk", "gst"}
        for note in guidance.values():
            assert "legal settlement" in note

        refreshed = db.session.get(JobInstruction, instruction.id)
        assert refreshed.status == "applied"
        assert refreshed.stage_applied == "analysis"
        assert set(refreshed.target_agents) == {"ratio", "cash_wc", "forecast", "risk", "gst"}
        assert "legal settlement" in refreshed.orchestrator_note

        # Visible in the same task-trace stream the frontend renders (GET /api/jobs/<id>/tasks).
        orchestrator_runs = TaskRun.query.filter_by(job_id=job.id, agent="orchestrator").all()
        assert len(orchestrator_runs) == 1
        assert "legal settlement" in orchestrator_runs[0].summary


def test_pending_instruction_only_offered_to_active_plan_template_modules(app):
    with app.app_context():
        # gst_reconciliation only runs GstComplianceAgent (see orchestrator/templates.py) --
        # ratio/cash_wc/forecast/risk must never be offered the instruction for this job.
        job = _make_job(app, plan_template="gst_reconciliation")
        llm = get_llm_gateway()
        instruction = JobInstruction(id=new_id("instr_"), job_id=job.id, content="Focus on Q4 GST mismatches.")
        db.session.add(instruction)
        db.session.commit()

        guidance = apply_pending_instructions(job, llm, stage="analysis")

        assert set(guidance.keys()) == {"gst"}


def test_instruction_not_relevant_to_data_stage_stays_pending_for_analysis(app):
    with app.app_context():
        job = _make_job(app)
        llm = get_llm_gateway()
        instruction = JobInstruction(id=new_id("instr_"), job_id=job.id, content="A note for later.")
        db.session.add(instruction)
        db.session.commit()

        # "data" stage's only offered agent is schema_mapper; the fake backend still applies
        # to whatever it's offered, so this exercises the data-stage branch specifically.
        guidance = apply_pending_instructions(job, llm, stage="data")
        assert set(guidance.keys()) == {"schema_mapper"}

        refreshed = db.session.get(JobInstruction, instruction.id)
        assert refreshed.status == "applied"
        assert refreshed.stage_applied == "data"
