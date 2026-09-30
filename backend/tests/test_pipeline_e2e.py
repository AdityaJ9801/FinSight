"""End-to-end pipeline test against the fake LLM backend and the seed CSVs (no live LLM
credentials, no Celery/Redis broker needed -- this calls the stage supervisors directly,
the same code Celery's tasks.py calls via .delay()/.run_stage(); only the message-broker
transport itself is untested here, since that requires an external Redis and is covered by
the manual walkthrough in README instead).
"""
import hashlib
import json
from pathlib import Path

from app.agents.analysis.supervisor import AnalysisSupervisor
from app.agents.data.supervisor import DataSupervisor
from app.agents.delivery.supervisor import DeliverySupervisor
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.document import Document
from app.models.report import Report
from app.models.tenant import Entity, Tenant
from app.orchestrator.orchestrator import create_job
from app.tools.report_render import lint_unbound_numbers
from app.utils import storage
from app.utils.ids import new_id

SEED_DIR = Path(__file__).parent.parent / "seed" / "data"
SEED_FILES = ["pnl.csv", "balance_sheet.csv", "cash_flow.csv", "bank_statement.csv"]


def _upload_seed_files(job) -> None:
    for name in SEED_FILES:
        content = (SEED_DIR / name).read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        uri = storage.write_bytes(f"{job.id}/raw/{name}", content)
        db.session.add(Document(
            id=new_id("doc_"), tenant_id=job.tenant_id, entity_id=job.entity_id, job_id=job.id,
            file_uri=uri, original_filename=name, sha256=sha256, status="uploaded",
        ))
    db.session.commit()


def test_full_pipeline_reaches_completed_report_with_no_unbound_numbers(app):
    with app.app_context():
        tenant = Tenant(id=new_id("ten_"), name="Test Tenant")
        db.session.add(tenant)
        db.session.flush()
        entity = Entity(id=new_id("ent_"), tenant_id=tenant.id, legal_name="Test Co")
        db.session.add(entity)
        db.session.commit()

        job = create_job(tenant.id, entity.id, created_by="tester", goal="test run")
        _upload_seed_files(job)

        llm = get_llm_gateway()

        data_passed = DataSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert data_passed, f"data stage did not pass: status={job.status}, error={job.error}"
        assert job.status == "DATA_VALIDATED"

        analysis_passed = AnalysisSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert analysis_passed

        delivery_passed = DeliverySupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert delivery_passed, f"delivery stage did not pass: status={job.status}, error={job.error}"
        assert job.status == "COMPLETED"

        report = Report.query.filter_by(dataset_version=job.dataset_version_id).first()
        assert report is not None
        assert report.verifier_status == "pass"
        assert report.html_uri and report.docx_uri and report.pdf_uri

        # lint_unbound_numbers runs on the DRAFT (placeholders still in {{m:...}} form) --
        # the verifier already enforced this before passing, but re-checking the actual
        # draft.json artifact here proves it, rather than trusting report.verifier_status
        # alone. Running the same lint against the final RESOLVED html would be meaningless:
        # every resolved number necessarily looks like a "raw number" at that point.
        draft = json.loads(storage.resolve(report.draft_uri).read_text())
        for section in draft["sections"]:
            assert lint_unbound_numbers(section["body"]) == []

        html = storage.resolve(report.html_uri).read_text(encoding="utf-8")
        assert "Rs." in html or "%" in html  # sanity: some resolved metric actually rendered
        assert "Data Diagnostic" in html
        assert "Virtual CFO" in html

        assert storage.resolve(report.docx_uri).exists()
        assert storage.resolve(report.pdf_uri).exists()
