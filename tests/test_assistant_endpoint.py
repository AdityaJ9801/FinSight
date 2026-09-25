"""POST /api/jobs/<id>/assistant: chat-driven, on-demand re-run of one of the job's own
analysis agents (e.g. "redo the risk score excluding the one-off item"), separate from the
fixed pipeline sequence and from /api/qa's pure-lookup behavior. Tested through the real
Flask test client against the fake LLM backend (deterministic: always picks the first
offered agent, no clarification -- see fake_client._assistant_decision).
"""
import hashlib
from pathlib import Path

from app.agents.analysis.supervisor import AnalysisSupervisor
from app.agents.data.supervisor import DataSupervisor
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.document import Document
from app.orchestrator.orchestrator import create_job
from app.utils import storage
from app.utils.default_tenant import DEFAULT_ENTITY_ID, DEFAULT_TENANT_ID, ensure_default_context
from app.utils.ids import new_id

SEED_DIR = Path(__file__).parent.parent / "seed" / "data"
SEED_FILES = ["pnl.csv", "balance_sheet.csv", "cash_flow.csv", "bank_statement.csv"]


def _make_validated_job(app):
    with app.app_context():
        # current_tenant_id()/_get_scoped_job always resolve to the fixed default tenant
        # (this is a "no login" direct app -- see api/deps.py), not whatever tenant a test
        # creates ad hoc -- unlike test_pipeline_e2e.py, this test goes through the real
        # HTTP/blueprint layer, which enforces that scoping, so it must match it.
        ensure_default_context()
        job = create_job(DEFAULT_TENANT_ID, DEFAULT_ENTITY_ID, created_by="tester", goal="test run")
        for name in SEED_FILES:
            content = (SEED_DIR / name).read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()
            uri = storage.write_bytes(f"{job.id}/raw/{name}", content)
            db.session.add(Document(
                id=new_id("doc_"), tenant_id=job.tenant_id, entity_id=job.entity_id, job_id=job.id,
                file_uri=uri, original_filename=name, sha256=sha256, status="uploaded",
            ))
        db.session.commit()

        llm = get_llm_gateway()
        assert DataSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert AnalysisSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        return job.id


def test_assistant_requires_a_validated_dataset(client, app):
    with app.app_context():
        ensure_default_context()
        job = create_job(DEFAULT_TENANT_ID, DEFAULT_ENTITY_ID, created_by="tester", goal="not yet run")
        job.dataset_version_id = None  # simulate "hasn't produced a validated dataset yet"
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/assistant", json={"message": "redo the risk score"})
    assert resp.status_code == 400
    assert "run the pipeline first" in resp.json["error"]


def test_assistant_runs_the_chosen_agent_and_records_a_task(client, app):
    job_id = _make_validated_job(app)

    resp = client.post(f"/api/jobs/{job_id}/assistant", json={
        "message": "Recompute the ratio trends excluding the one-off item.",
    })
    assert resp.status_code == 200
    data = resp.json
    assert data["type"] == "answer"
    assert data["agent_used"] in {"ratio", "cash_wc", "forecast", "risk"}  # whichever full_analysis offers first
    assert data["status"] in {"done", "partial"}
    # No {{m:...}} placeholder should survive -- resolve_placeholders should have expanded it.
    assert "{{m:" not in data["answer"]

    tasks = client.get(f"/api/jobs/{job_id}/tasks").json
    matching = [t for t in tasks if t["agent"] == data["agent_used"]]
    assert len(matching) >= 1, "the on-demand agent run should show up in the task trace like any other"


def test_assistant_follow_up_with_explicit_chosen_agent_skips_the_routing_call(client, app):
    job_id = _make_validated_job(app)

    resp = client.post(f"/api/jobs/{job_id}/assistant", json={
        "chosen_agent": "risk", "action_note": "Focus on the anomaly flags only.",
    })
    assert resp.status_code == 200
    assert resp.json["agent_used"] == "risk"


def test_assistant_rejects_an_agent_not_in_this_jobs_plan_template(client, app):
    job_id = _make_validated_job(app)  # full_analysis includes ratio/cash_wc/forecast/risk/gst

    resp = client.post(f"/api/jobs/{job_id}/assistant", json={"chosen_agent": "not_a_real_agent"})
    assert resp.status_code == 400
