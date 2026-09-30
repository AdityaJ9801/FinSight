"""Endpoints added for the React web app: the job list, richer job detail, and the health score."""
from datetime import date

from app.extensions import db
from app.models.dataset import DatasetVersion
from app.models.document import Document
from app.models.metric import Metric
from app.models.tenant import Tenant
from app.orchestrator.orchestrator import create_job
from app.utils.default_tenant import DEFAULT_TENANT_ID
from app.utils.ids import new_id


def _job(app, goal="web test", with_metrics=False):
    with app.app_context():
        if db.session.get(Tenant, DEFAULT_TENANT_ID) is None:
            db.session.add(Tenant(id=DEFAULT_TENANT_ID, name="Default"))
            db.session.commit()
        job = create_job(DEFAULT_TENANT_ID, None, created_by=None, goal=goal)
        db.session.add(Document(
            id=new_id("doc_"), tenant_id=DEFAULT_TENANT_ID, job_id=job.id, file_uri="x",
            original_filename="pnl.csv", sha256="0" * 64, status="uploaded",
        ))
        if with_metrics:
            dv = db.session.get(DatasetVersion, job.dataset_version_id)
            assert dv is not None
            for code, period, value in [
                ("current_ratio", date(2023, 3, 31), 1.2),
                ("current_ratio", date(2024, 3, 31), 2.1),  # latest period wins
                ("debt_to_equity", date(2024, 3, 31), 0.4),
            ]:
                db.session.add(Metric(id=new_id("met_"), dataset_version=dv.id, metric_code=code,
                                      period_end=period, value=value, unit="x", formula_version="1.0"))
        db.session.commit()
        return job.id


def test_list_jobs_returns_newest_first_with_document_counts(app, client):
    first = _job(app, goal="first")
    second = _job(app, goal="second")
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    stamps = [j["created_at"] for j in resp.json]
    assert stamps == sorted(stamps, reverse=True)
    assert {first, second} <= {j["id"] for j in resp.json}
    row = next(j for j in resp.json if j["id"] == first)
    assert row["goal"] == "first"
    assert row["plan_template"] == "full_analysis"
    assert row["document_count"] == 1


def test_get_job_includes_goal_and_documents(app, client):
    job_id = _job(app, goal="detail")
    body = client.get(f"/api/jobs/{job_id}").json
    assert body["goal"] == "detail"
    assert body["created_at"]
    assert [d["filename"] for d in body["documents"]] == ["pnl.csv"]


def test_health_scores_latest_period_of_each_metric(app, client):
    job_id = _job(app, with_metrics=True)
    body = client.get(f"/api/jobs/{job_id}/health").json
    by_code = {b["metric_code"]: b for b in body["breakdown"]}
    assert by_code["current_ratio"]["points"] == 20  # 2.1 (FY24), not 1.2 (FY23)
    assert by_code["debt_to_equity"]["points"] == 20
    assert by_code["dso"]["included"] is False
    assert 0 <= body["score"] <= 100 and body["rating"]


def test_health_is_404_before_metrics_exist(app, client):
    job_id = _job(app)
    assert client.get(f"/api/jobs/{job_id}/health").status_code == 404
