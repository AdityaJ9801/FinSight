from datetime import datetime, timezone

from app.extensions import db
from app.utils.ids import new_id

DOC_TYPES = (
    "balance_sheet", "pnl", "trial_balance", "bank_statement", "gstr_3b", "gstr_2b",
    "ageing_ar", "ageing_ap", "loan_schedule", "inventory", "other",
)


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("doc_"))
    tenant_id = db.Column(db.String(36), db.ForeignKey("tenants.id"), nullable=False, index=True)
    entity_id = db.Column(db.String(36), db.ForeignKey("entities.id"), nullable=True, index=True)
    job_id = db.Column(db.String(36), db.ForeignKey("jobs.id"), nullable=False, index=True)

    file_uri = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    # Not globally unique per tenant: unlike the design doc's Postgres schema, a Document
    # row here is job-scoped (job_id is required, one row per upload), so the same file
    # content re-uploaded for a *different* job is a legitimate second row, not a conflict.
    # `duplicate_of` still records the match for provenance/analyst awareness.
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    mime = db.Column(db.String(120), nullable=True)
    pages = db.Column(db.Integer, nullable=True)

    doc_type = db.Column(db.String(40), nullable=True)
    period_start = db.Column(db.Date, nullable=True)
    period_end = db.Column(db.Date, nullable=True)
    unit_scale = db.Column(db.Numeric(20, 6), default=1)  # 1, 1e3, 1e5 (lakh), 1e7 (crore)
    currency = db.Column(db.String(3), default="INR")
    layout_id = db.Column(db.String(120), nullable=True)

    status = db.Column(db.String(30), default="uploaded")
    duplicate_of = db.Column(db.String(36), db.ForeignKey("documents.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
