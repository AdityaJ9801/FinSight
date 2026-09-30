"""A bank-statement-only analysis must run end to end. It used to stop at a NO_FACTS review
forever: bank transactions aren't statement facts, and accepting the review re-blocked it."""
import hashlib
from datetime import date
from pathlib import Path

from app.agents.analysis.supervisor import AnalysisSupervisor
from app.agents.data.supervisor import DataSupervisor
from app.agents.delivery.supervisor import DeliverySupervisor
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.document import Document
from app.models.metric import Metric
from app.models.report import Report
from app.models.review import ReviewItem
from app.models.tenant import Entity, Tenant
from app.orchestrator.orchestrator import create_job
from app.tools.calc.bank_metrics import compute_bank_metrics, payer_key
from app.utils import storage
from app.utils.ids import new_id

SEED = Path(__file__).parent.parent / "seed" / "data"


def _job_with(app, files, template):
    tenant = Tenant(id=new_id("ten_"), name="T")
    db.session.add(tenant)
    db.session.flush()
    entity = Entity(id=new_id("ent_"), tenant_id=tenant.id, legal_name="Co")
    db.session.add(entity)
    db.session.commit()
    job = create_job(tenant.id, entity.id, created_by="tester", goal="bank test", plan_template=template)
    for name, content in files:
        uri = storage.write_bytes(f"{job.id}/raw/{name}", content)
        db.session.add(Document(id=new_id("doc_"), tenant_id=tenant.id, entity_id=entity.id, job_id=job.id,
                                file_uri=uri, original_filename=name, sha256=hashlib.sha256(content).hexdigest(),
                                status="uploaded"))
    db.session.commit()
    return job


def test_bank_statement_only_analysis_completes_with_cash_metrics(app):
    with app.app_context():
        job = _job_with(app, [("bank_statement.csv", (SEED / "bank_statement.csv").read_bytes())], "bank_statement_review")
        llm = get_llm_gateway()

        assert DataSupervisor(app, llm).run_stage(job, job.dataset_version_id), job.progress_message
        assert AnalysisSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert DeliverySupervisor(app, llm).run_stage(job, job.dataset_version_id), job.error
        assert job.status == "COMPLETED"

        codes = {m.metric_code for m in Metric.query.filter_by(dataset_version=job.dataset_version_id)}
        assert {"bank_inflows", "bank_outflows", "bank_closing_balance", "bank_cash_cover_months", "risk_score"} <= codes
        closing = Metric.query.filter_by(dataset_version=job.dataset_version_id, metric_code="bank_closing_balance",
                                         period_end=date(2024, 3, 31)).one()
        assert float(closing.value) == 910000  # last balance in the seed statement
        report = Report.query.filter_by(dataset_version=job.dataset_version_id).first()
        assert report is not None and report.html_uri

        # Statement analysis still runs on bank transactions alone (monthly flows, counterparties).
        from app.orchestrator import blackboard

        analysis = blackboard.read(job.id, "detailed_analysis")
        assert analysis is not None and analysis["bank"]["totals"]["months"] == 12


def test_accepted_no_data_fails_cleanly_instead_of_looping(app):
    with app.app_context():
        job = _job_with(app, [("notes.csv", b"Remarks\nNothing numeric here\n")], "full_analysis")
        llm = get_llm_gateway()

        assert not DataSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert job.status == "AWAITING_REVIEW"
        item = ReviewItem.query.filter_by(job_id=job.id, kind="reconciliation", status="open").one()
        assert item.payload["check_code"] == "NO_FACTS"

        item.status = "resolved"  # the reviewer accepts it
        db.session.commit()
        job.status = "MAPPING"
        assert not DataSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert job.status == "FAILED"
        assert "No usable financial data" in job.error
        assert ReviewItem.query.filter_by(job_id=job.id, status="open").count() == 0


def test_same_periods_in_two_analyses_keep_separate_metrics(app):
    with app.app_context():
        files = [(n, (SEED / n).read_bytes()) for n in ("pnl.csv", "balance_sheet.csv")]
        first = _job_with(app, files, "full_analysis")
        second = _job_with(app, files, "full_analysis")
        llm = get_llm_gateway()
        for job in (first, second):
            DataSupervisor(app, llm).run_stage(job, job.dataset_version_id)
            AnalysisSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        # Metric ids used to be global per (code, period), so the second job took over the first's rows.
        assert Metric.query.filter_by(dataset_version=first.dataset_version_id).count() > 0
        assert (Metric.query.filter_by(dataset_version=first.dataset_version_id).count()
                == Metric.query.filter_by(dataset_version=second.dataset_version_id).count())


def test_bank_metrics_math():
    rows = compute_bank_metrics([
        {"txn_date": date(2024, 1, 3), "credit": 100, "debit": 0, "balance": 100, "narration": "NEFT Acme Ltd 8812"},
        {"txn_date": date(2024, 1, 20), "credit": 0, "debit": 30, "balance": 70, "narration": "Rent"},
        {"txn_date": date(2024, 2, 4), "credit": 50, "debit": 0, "balance": 120, "narration": "UPI Beta Co"},
        {"txn_date": date(2024, 2, 9), "credit": 0, "debit": 90, "balance": 30, "narration": "Salaries"},
    ])
    get = {(r["metric_code"], r["period_end"]): r["value"] for r in rows}
    jan, feb = date(2024, 1, 31), date(2024, 2, 29)
    assert get[("bank_net_flow", jan)] == 70 and get[("bank_net_flow", feb)] == -40
    assert get[("bank_closing_balance", feb)] == 30
    assert get[("bank_cash_cover_months", feb)] == 30 / 60  # closing / average monthly outflow
    assert get[("bank_top_payer_share", feb)] == 100 / 150
    assert get[("bank_negative_month_share", feb)] == 0.5
    assert payer_key("NEFT CR Acme Ltd 8812", None) == payer_key("Acme Ltd", None) == "acme ltd"
