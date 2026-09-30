"""Adding statements to an analysis, company profile + peer benchmarks, and grounded chat."""
import io
from datetime import date
from pathlib import Path

import pytest

from app.agents.analysis.supervisor import AnalysisSupervisor
from app.agents.data.supervisor import DataSupervisor
from app.agents.delivery.qa import QAAgent
from app.domain.benchmarks import compare
from app.domain.chat_intent import is_action_request
from app.domain.metric_facts import match_metrics
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.dataset import DatasetVersion
from app.models.job import Job
from app.models.metric import Metric
from app.models.review import ReviewItem
from app.models.tenant import Tenant
from app.tools.calc.metrics import persist_metrics
from app.utils.default_tenant import DEFAULT_TENANT_ID

SEED = Path(__file__).parent.parent / "seed" / "data"


@pytest.fixture()
def no_queue(monkeypatch):
    """Records start() calls instead of enqueueing Celery tasks (no Redis in tests)."""
    started = []
    monkeypatch.setattr("app.api.jobs.start", lambda job: started.append(job.id))
    return started


def _default_tenant(app):
    with app.app_context():
        if db.session.get(Tenant, DEFAULT_TENANT_ID) is None:
            db.session.add(Tenant(id=DEFAULT_TENANT_ID, name="Default"))
            db.session.commit()


def _upload(client, names, **form):
    data = {"goal": "test", "plan_template": "full_analysis", **form,
            "files": [(io.BytesIO((SEED / n).read_bytes()), n) for n in names]}
    return client.post("/api/jobs", data=data, content_type="multipart/form-data")


def test_create_job_saves_company_profile(app, client, no_queue):
    _default_tenant(app)
    resp = _upload(client, ["pnl.csv"], company_name="Acme Pvt Ltd", industry="manufacturing")
    assert resp.status_code == 201
    job = client.get(f"/api/jobs/{resp.json['job_id']}").json
    assert job["company_name"] == "Acme Pvt Ltd" and job["industry"] == "manufacturing"
    assert _upload(client, ["pnl.csv"], industry="not_a_sector").status_code == 400
    bad = client.post("/api/jobs", data={"files": [(io.BytesIO(b"x"), "notes.docx")]}, content_type="multipart/form-data")
    assert bad.status_code == 400 and "unsupported" in bad.json["error"]


def test_add_statements_creates_new_dataset_version_and_reruns(app, client, no_queue):
    _default_tenant(app)
    job_id = _upload(client, ["pnl.csv"]).json["job_id"]
    with app.app_context():
        job = db.session.get(Job, job_id)
        first_version = job.dataset_version_id
        job.status = "COMPLETED"
        db.session.add(ReviewItem(id="rev_old", job_id=job_id, kind="reconciliation", status="resolved",
                                  payload={"check_code": "BS_TIE"}))
        db.session.commit()

    resp = client.post(f"/api/jobs/{job_id}/documents", content_type="multipart/form-data",
                       data={"files": [(io.BytesIO((SEED / "pnl.csv").read_bytes()), "pnl.csv"),
                                       (io.BytesIO((SEED / "balance_sheet.csv").read_bytes()), "balance_sheet.csv")]})
    assert resp.status_code == 202
    assert resp.json["added"] == ["balance_sheet.csv"] and resp.json["skipped"] == ["pnl.csv"]
    assert no_queue[-1] == job_id

    with app.app_context():
        job = db.session.get(Job, job_id)
        assert job.dataset_version_id != first_version
        version = db.session.get(DatasetVersion, job.dataset_version_id)
        assert version.parent_version == first_version
        assert job.stage == "data" and job.error is None
        # An accepted reconciliation from the old data must not auto-accept against the new data.
        assert db.session.get(ReviewItem, "rev_old").status == "superseded"

    detail = client.get(f"/api/jobs/{job_id}").json
    assert detail["dataset_versions"] == 2
    assert sorted(d["filename"] for d in detail["documents"]) == ["balance_sheet.csv", "pnl.csv"]


def test_add_statements_rejected_while_running_or_duplicate(app, client, no_queue):
    _default_tenant(app)
    job_id = _upload(client, ["pnl.csv"]).json["job_id"]
    with app.app_context():
        db.session.get(Job, job_id).status = "ANALYZING"
        db.session.commit()
    files = {"files": [(io.BytesIO((SEED / "cash_flow.csv").read_bytes()), "cash_flow.csv")]}
    assert client.post(f"/api/jobs/{job_id}/documents", data=files, content_type="multipart/form-data").status_code == 409
    with app.app_context():
        db.session.get(Job, job_id).status = "COMPLETED"
        db.session.commit()
    dup = {"files": [(io.BytesIO((SEED / "pnl.csv").read_bytes()), "pnl.csv")]}
    assert client.post(f"/api/jobs/{job_id}/documents", data=dup, content_type="multipart/form-data").status_code == 400


def test_delete_removes_every_dataset_version(app, client, no_queue):
    _default_tenant(app)
    job_id = _upload(client, ["pnl.csv"]).json["job_id"]
    with app.app_context():
        db.session.get(Job, job_id).status = "COMPLETED"
        db.session.commit()
    client.post(f"/api/jobs/{job_id}/documents", content_type="multipart/form-data",
                data={"files": [(io.BytesIO((SEED / "cash_flow.csv").read_bytes()), "cash_flow.csv")]})
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    with app.app_context():
        assert DatasetVersion.query.filter_by(job_id=job_id).count() == 0


def test_benchmarks_place_company_in_quartiles(app, client, no_queue):
    _default_tenant(app)
    job_id = _upload(client, ["pnl.csv"], industry="manufacturing").json["job_id"]
    with app.app_context():
        job = db.session.get(Job, job_id)
        persist_metrics(job.dataset_version_id, [
            {"metric_code": "current_ratio", "period_end": date(2024, 3, 31), "value": 2.5, "unit": "x",
             "formula_version": "1.0", "inputs": []},
            {"metric_code": "debt_to_equity", "period_end": date(2024, 3, 31), "value": 2.0, "unit": "x",
             "formula_version": "1.0", "inputs": []},
        ])
    body = client.get(f"/api/jobs/{job_id}/benchmarks").json
    items = {i["metric_code"]: i for i in body["items"]}
    assert items["current_ratio"]["quartile"] == 4 and items["current_ratio"]["verdict"] == "better"
    # Lower is better for leverage: a high D/E is worse than peers, not better.
    assert items["debt_to_equity"]["verdict"] == "worse"
    assert "indicative" in body["source"]
    assert client.get(f"/api/jobs/{job_id}/benchmarks?industry=nope").status_code == 400
    assert len(client.get("/api/benchmarks/industries").json["industries"]) >= 8
    assert compare("nope", {}) is None


def test_chat_questions_are_not_treated_as_reruns():
    assert not is_action_request("Why did the EBITDA margin change?")
    assert not is_action_request("What are the biggest risks for a lender?")
    assert is_action_request("Re-run the risk score excluding one-off items")
    assert is_action_request("What if revenue falls 10%?")
    assert match_metrics("Is working capital getting tighter?")[:4] == ["dso", "dio", "dpo", "cash_conversion_cycle"]


def test_assistant_hands_questions_back_to_qa(app, client):
    _default_tenant(app)
    with app.app_context():
        from app.orchestrator.orchestrator import create_job

        job = create_job(DEFAULT_TENANT_ID, None, None, "q")
        job_id = job.id
    resp = client.post(f"/api/jobs/{job_id}/assistant", json={"message": "Why did the EBITDA margin change?"})
    assert resp.status_code == 200
    assert resp.json["agent_used"] is None and resp.json["route"] == "question"


def test_make_the_report_from_chat_regenerates_and_republishes(app, client):
    """'make the report' used to get a canned "use the Chat Assistant" reply. It must re-run the
    report writer, re-verify, and publish a new revision that the report endpoint serves."""
    from app.agents.delivery.supervisor import DeliverySupervisor
    from app.models.document import Document
    from app.models.report import Report
    from app.orchestrator.orchestrator import create_job
    from app.utils import storage
    from app.utils.ids import new_id

    _default_tenant(app)
    with app.app_context():
        job = create_job(DEFAULT_TENANT_ID, None, None, "chat report")
        for name in ("pnl.csv", "balance_sheet.csv"):
            content = (SEED / name).read_bytes()
            db.session.add(Document(id=new_id("doc_"), tenant_id=DEFAULT_TENANT_ID, job_id=job.id,
                                    file_uri=storage.write_bytes(f"{job.id}/raw/{name}", content),
                                    original_filename=name, sha256=name * 4, status="uploaded"))
        db.session.commit()
        llm = get_llm_gateway()
        assert DataSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert AnalysisSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert DeliverySupervisor(app, llm).run_stage(job, job.dataset_version_id)
        job_id, dsv = job.id, job.dataset_version_id
        before = Report.query.filter_by(dataset_version=dsv).one().revision or 0

    resp = client.post(f"/api/jobs/{job_id}/assistant", json={"message": "make the report"})
    assert resp.status_code == 200, resp.json
    assert resp.json["agent_used"] == "report_writer"
    with app.app_context():
        assert Report.query.filter_by(dataset_version=dsv).one().revision == before + 1
    assert client.get(f"/api/jobs/{job_id}/report?format=html").status_code == 200


def test_qa_answer_quotes_verified_figures_and_resolves_bindings(app):
    _default_tenant(app)
    with app.app_context():
        from app.orchestrator.orchestrator import create_job
        from app.utils import storage
        from app.models.document import Document
        from app.utils.ids import new_id

        job = create_job(DEFAULT_TENANT_ID, None, None, "qa")
        for name in ("pnl.csv", "balance_sheet.csv"):
            content = (SEED / name).read_bytes()
            db.session.add(Document(id=new_id("doc_"), tenant_id=DEFAULT_TENANT_ID, job_id=job.id,
                                    file_uri=storage.write_bytes(f"{job.id}/raw/{name}", content),
                                    original_filename=name, sha256=name * 4, status="uploaded"))
        db.session.commit()
        llm = get_llm_gateway()
        DataSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        AnalysisSupervisor(app, llm).run_stage(job, job.dataset_version_id)

        current = Metric.query.filter_by(dataset_version=job.dataset_version_id, metric_code="current_ratio") \
            .order_by(Metric.period_end.desc()).first()
        res = QAAgent(llm).answer(DEFAULT_TENANT_ID, job.dataset_version_id, "How is liquidity looking?")
        assert f"{float(current.value):.2f}x" in res["answer"]
        assert "current_ratio" in res["citations"]

        risks = QAAgent(llm).answer(DEFAULT_TENANT_ID, job.dataset_version_id, "What are the biggest risks for a lender?")
        assert "What the analysis flagged" in risks["answer"]
        assert "{{m:" not in risks["answer"]
