from datetime import date
from app.agents.base import TaskSpec
from app.agents.data.verification_advisor import VerificationAdvisorAgent
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.dataset import DatasetVersion, FinancialFact
from app.models.document import Document
from app.models.job import Job
from app.models.review import ReviewItem
from app.models.tenant import Tenant
from app.utils.ids import new_id


def _setup_job(goal="Test analysis"):
    tenant = Tenant.query.first()
    if not tenant:
        tenant = Tenant(id="t_test", name="Test Tenant")
        db.session.add(tenant)
        db.session.commit()
    job = Job(id=new_id("j_"), tenant_id=tenant.id, goal=goal, status="AWAITING_REVIEW")
    dv = DatasetVersion(id=new_id("dv_"), job_id=job.id)
    job.dataset_version_id = dv.id
    db.session.add_all([job, dv])
    db.session.commit()
    return job, dv


def test_verification_advisor_mapping_recommendations(app):
    with app.app_context():
        fake_llm = get_llm_gateway()
        job, dv = _setup_job("Mapping test")

        doc = Document(id=new_id("d_"), job_id=job.id, tenant_id=job.tenant_id,
                       original_filename="P_and_L.csv", doc_type="pnl", file_uri="file://test.csv", sha256="fake_sha256")
        db.session.add(doc)
        db.session.commit()

        # A mapping review item with an ambiguous label
        item = ReviewItem(
            id=new_id("rev_"), job_id=job.id, kind="mapping",
            payload={
                "document_id": doc.id,
                "label": "Cost of Goods Sold (COGS)",
                "section": "Direct Costs",
                "suggested_account_id": "PL.OTHER_EXPENSES",
                "confidence": 0.5,
            }
        )
        db.session.add(item)
        db.session.commit()

        advisor = VerificationAdvisorAgent(fake_llm)
        spec = TaskSpec(
            task_id="t_test_adv", job_id=job.id, tenant_id=job.tenant_id, agent="verification_advisor",
            goal="mapping advice", params={"job_id": job.id, "auto_resolve": False}
        )
        res = advisor.run(spec)

        assert res.status.value == "done"
        updated_item = ReviewItem.query.get(item.id)
        assert "recommendation" in updated_item.payload
        rec = updated_item.payload["recommendation"]
        assert rec["suggested_account_id"] == "PL.COGS"
        assert rec["confidence"] >= 0.9
        assert rec["auto_resolvable"] is True


def test_verification_advisor_reconciliation_recommendations(app):
    with app.app_context():
        fake_llm = get_llm_gateway()
        job, dv = _setup_job("Reconciliation test")

        # Reconciliation failure item: internal 16,000 addition mismatch in FY2020
        item = ReviewItem(
            id=new_id("rev_"), job_id=job.id, kind="reconciliation",
            payload={
                "check_code": "PL_CASCADE",
                "expected": 1816610.0,
                "actual": 1800610.0,
                "diff": 16000.0,
                "explanation": "Calculated total expenses mismatch with reported statement total."
            }
        )
        db.session.add(item)
        db.session.commit()

        advisor = VerificationAdvisorAgent(fake_llm)
        spec = TaskSpec(
            task_id="t_test_adv_recon", job_id=job.id, tenant_id=job.tenant_id, agent="verification_advisor",
            goal="reconciliation advice", params={"job_id": job.id, "auto_resolve": False}
        )
        res = advisor.run(spec)

        assert res.status.value == "done"
        updated_item = ReviewItem.query.get(item.id)
        rec = updated_item.payload["recommendation"]
        assert rec["action"] == "accept"
        assert rec["auto_resolvable"] is True
        assert "16,000" in rec["reasoning"] or "addition" in rec["reasoning"].lower()


def test_verification_advisor_auto_resolve(app):
    with app.app_context():
        fake_llm = get_llm_gateway()
        job, dv = _setup_job("Auto resolve test")

        doc = Document(id=new_id("d_"), job_id=job.id, tenant_id=job.tenant_id,
                       original_filename="statement.xlsx", doc_type="pnl", file_uri="file://statement.xlsx", sha256="fake_sha256")
        db.session.add(doc)
        db.session.commit()

        fact = FinancialFact(
            dataset_version=dv.id, entity_id="ent_1",
            account_id="PL.OTHER_EXPENSES", period_end=date(2022, 3, 31),
            value=2766207.75, currency="INR", source_doc=doc.id, confidence=0.5
        )
        db.session.add(fact)

        item = ReviewItem(
            id=new_id("rev_"), job_id=job.id, kind="mapping",
            payload={
                "document_id": doc.id,
                "label": "Cost of Materials Consumed",
                "section": "Expenses",
                "suggested_account_id": "PL.OTHER_EXPENSES",
                "confidence": 0.5,
            }
        )
        db.session.add(item)
        db.session.commit()

        advisor = VerificationAdvisorAgent(fake_llm)
        spec = TaskSpec(
            task_id="t_test_autoresolve", job_id=job.id, tenant_id=job.tenant_id, agent="verification_advisor",
            goal="auto resolve", params={"job_id": job.id, "auto_resolve": True}
        )
        res = advisor.run(spec)


        assert res.status.value == "done"
        # Item should now be resolved
        updated_item = ReviewItem.query.get(item.id)
        assert updated_item.status == "resolved"
        assert updated_item.resolution["account_id"] == "PL.COGS"

        # Fact should now be re-mapped to PL.COGS
        updated_fact = FinancialFact.query.get(fact.id)
        assert updated_fact.account_id == "PL.COGS"
        assert updated_fact.confidence == 1.0


def test_verification_advisor_verification_review_item(app):
    with app.app_context():
        fake_llm = get_llm_gateway()
        job, dv = _setup_job("Verification review test")
        job.status = "NEEDS_ANALYST"
        db.session.commit()

        item = ReviewItem(
            id=new_id("rev_"), job_id=job.id, kind="verification",
            payload={
                "check_code": "VERIFIER_DISCREPANCY",
                "issues": ["Unbound claims in executive summary", "Unverified ratio Gross Margin"],
                "explanation": "Flagged discrepancies require analyst review.",
                "summary": "Report draft requires analyst verification sign-off",
            }
        )
        db.session.add(item)
        db.session.commit()

        advisor = VerificationAdvisorAgent(fake_llm)
        spec = TaskSpec(
            task_id="t_test_verif_resolve", job_id=job.id, tenant_id=job.tenant_id, agent="verification_advisor",
            goal="auto resolve verification", params={"job_id": job.id, "auto_resolve": True}
        )
        res = advisor.run(spec)

        assert res.status.value == "done"
        updated_item = ReviewItem.query.get(item.id)
        assert updated_item.status == "resolved"
        assert "note" in updated_item.resolution

        updated_job = Job.query.get(job.id)
        assert updated_job.status == "COMPLETED"
        assert updated_job.progress_pct == 100
