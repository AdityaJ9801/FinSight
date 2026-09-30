"""Detailed statement analysis: the analytics engine, its pipeline artifacts, the report's
supporting-tables section, and the /analysis API endpoint."""
from datetime import date

import pytest

from app.agents.analysis.supervisor import AnalysisSupervisor
from app.agents.data.supervisor import DataSupervisor
from app.agents.delivery.supervisor import DeliverySupervisor
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.report import Report
from app.models.tenant import Entity, Tenant
from app.orchestrator import blackboard
from app.orchestrator.orchestrator import create_job
from app.tools.calc import detailed_analysis as analytics
from app.utils import storage
from app.utils.ids import new_id
from tests.test_pipeline_e2e import _upload_seed_files

FY23, FY24 = date(2023, 3, 31), date(2024, 3, 31)
FACTS = {
    FY23: {"PL.REVENUE": 1000.0, "PL.OTHER_INCOME": 10.0, "PL.COGS": 600.0, "PL.EMPLOYEE_COST": 150.0,
           "PL.OTHER_EXPENSES": 80.0, "PL.DEPRECIATION": 30.0, "PL.FINANCE_COST": 20.0, "PL.TAX": 32.5,
           "PL.PAT": 97.5, "BS.TOTAL_ASSETS": 1020.0, "BS.EQ.TOTAL": 480.0, "BS.CA.TOTAL": 400.0, "BS.CL.TOTAL": 220.0},
    FY24: {"PL.REVENUE": 1200.0, "PL.OTHER_INCOME": 12.0, "PL.COGS": 700.0, "PL.EMPLOYEE_COST": 180.0,
           "PL.OTHER_EXPENSES": 90.0, "PL.DEPRECIATION": 35.0, "PL.FINANCE_COST": 25.0, "PL.TAX": 45.5,
           "PL.PAT": 136.5, "BS.TOTAL_ASSETS": 1150.0, "BS.EQ.TOTAL": 616.5, "BS.CA.TOTAL": 475.0, "BS.CL.TOTAL": 225.0},
}


# --------------------------------------------------------------------------- analytics

def test_profit_bridge_foots_to_reported_pat():
    bridge = analytics.profit_bridge(FACTS)
    steps = bridge["steps"]
    assert steps[0]["amount"] == 97.5 and steps[-1]["amount"] == 136.5
    assert sum(s["amount"] for s in steps if s["kind"] != "end") == pytest.approx(136.5)
    assert abs(bridge["unexplained"]) < 1e-9
    by_label = {s["label"]: s["amount"] for s in steps}
    assert by_label["Revenue"] == 200.0 and by_label["Cost of materials"] == -100.0


def test_profit_bridge_shows_unexplained_residual_explicitly():
    facts = {FY23: dict(FACTS[FY23]), FY24: dict(FACTS[FY24])}
    facts[FY24]["PL.PAT"] += 5.0  # a PAT the lines don't explain (e.g. a mis-mapped caption)
    bridge = analytics.profit_bridge(facts)
    steps = bridge["steps"]
    assert steps[-2]["label"] == "Unreconciled difference" and steps[-2]["amount"] == pytest.approx(5.0)
    assert bridge["reconciled"] is False  # flagged, never passed off as a normal bridge step
    assert sum(s["amount"] for s in steps if s["kind"] != "end") == pytest.approx(steps[-1]["amount"])


def test_cagr_uses_whole_fiscal_years_and_rejects_sign_changes():
    growth = {g["label"]: g for g in analytics.growth(FACTS)}
    assert growth["Revenue"]["years"] == 1.0  # FY23->FY24 spans a leap day; still exactly one year
    assert growth["Revenue"]["cagr"] == pytest.approx(0.2)
    assert analytics.cagr(-10.0, 50.0, 2.0) is None and analytics.cagr(10.0, 50.0, 0.1) is None
    assert analytics.cagr(100.0, 121.0, 2.0) == pytest.approx(0.1)


def test_dupont_factors_multiply_back_to_roe():
    for row in analytics.dupont(FACTS):
        f = FACTS[date.fromisoformat(row["period"])]
        assert row["roe"] == pytest.approx(f["PL.PAT"] / f["BS.EQ.TOTAL"])


def test_common_size_and_horizontal_analysis():
    pl = {r["account_id"]: r for r in analytics.statement_analysis(FACTS)["PL"]}
    assert pl["PL.COGS"]["common_size"]["2023-03-31"] == pytest.approx(0.6)
    assert pl["PL.REVENUE"]["change_pct"]["2024-03-31"] == pytest.approx(0.2)
    assert pl["PL.REVENUE"]["change"]["2024-03-31"] == 200.0


def test_bank_analytics_monthly_rollup():
    txns = [{"txn_date": "2023-04-05", "narration": "Salary", "debit": 100, "credit": 0, "balance": 900},
            {"txn_date": "2023-04-20", "narration": "Customer A", "debit": 0, "credit": 300, "balance": 1200},
            {"txn_date": "2023-05-02", "narration": "Customer A", "debit": 0, "credit": 50, "balance": 1250}]
    bank = analytics.bank_analytics(txns)
    assert [m["month"] for m in bank["monthly"]] == ["2023-04", "2023-05"]
    assert bank["monthly"][0]["net"] == 200 and bank["monthly"][0]["closing_balance"] == 1200
    assert bank["top_inflows"][0] == {"counterparty": "Customer A", "amount": 350.0, "share": 1.0}
    assert bank["totals"]["net"] == 250


# ------------------------------------------------------------------ pipeline fixture

@pytest.fixture()
def completed_job(app):
    with app.app_context():
        tenant = Tenant(id=new_id("ten_"), name="T")
        db.session.add(tenant)
        db.session.flush()
        entity = Entity(id=new_id("ent_"), tenant_id=tenant.id, legal_name="Co")
        db.session.add(entity)
        db.session.commit()
        job = create_job(tenant.id, entity.id, created_by="t", goal="detailed analysis test")
        _upload_seed_files(job)
        llm = get_llm_gateway()
        assert DataSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert AnalysisSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert DeliverySupervisor(app, llm).run_stage(job, job.dataset_version_id)
        yield job


def test_pipeline_produces_detailed_analysis_and_report_tables(app, completed_job):
    job = completed_job
    with app.app_context():
        analysis = blackboard.read(job.id, "detailed_analysis")
        assert analysis["profit_bridge"]["to_period"] == "2024-03-31"
        assert {g["label"] for g in analysis["growth"]} >= {"Revenue", "PAT"}

        report = Report.query.filter_by(dataset_version=job.dataset_version_id).first()
        html = storage.resolve(report.html_uri).read_text(encoding="utf-8")
        assert "Detailed Statement Analysis — Supporting Tables" in html
        assert "Profit bridge" in html and "DuPont decomposition" in html
        assert "Power BI" not in html
        # section order: narrative -> supporting tables -> data diagnostic
        assert html.index("Supporting Tables") < html.index("Virtual CFO Data Diagnostic")
        # the taxonomy alias fix: risk findings are stored as "risk_anomaly" but now get a section
        draft = blackboard.read(job.id, "draft")
        assert "Risk Assessment & Anomaly Flags" in [s["heading"] for s in draft["sections"]]


def test_agents_and_analysis_api(app, client, completed_job):
    job_id = completed_job.id
    agents = client.get("/api/agents").get_json()
    by_name = {a["name"]: a for a in agents}
    assert by_name["report_writer"]["depends_on"] == ["insight_reasoner", "chart_spec"]
    assert by_name["detailed_analytics"]["stage"] == "analysis" and "class_path" not in by_name["detailed_analytics"]
    assert "powerbi_publisher" not in by_name

    # jobs are tenant-scoped: re-point the test job at the API's default tenant
    with app.app_context():
        from app.api.deps import current_tenant_id
        from app.models.job import Job
        db.session.get(Job, job_id).tenant_id = current_tenant_id()
        db.session.commit()

    assert client.get(f"/api/jobs/{job_id}/analysis").get_json()["periods"] == ["2023-03-31", "2024-03-31"]
    assert client.get("/api/jobs/job_missing/analysis").status_code == 404
