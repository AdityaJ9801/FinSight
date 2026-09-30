from datetime import datetime, timezone

from app.extensions import db
from app.utils.ids import new_id


class DatasetVersion(db.Model):
    __tablename__ = "dataset_versions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("dsv_"))
    entity_id = db.Column(db.String(36), db.ForeignKey("entities.id"), nullable=True, index=True)
    job_id = db.Column(db.String(36), db.ForeignKey("jobs.id"), nullable=False, index=True)
    status = db.Column(db.String(30), default="DRAFT")  # DRAFT|VALIDATED|VALIDATED_WITH_GAPS|REJECTED
    parent_version = db.Column(db.String(36), db.ForeignKey("dataset_versions.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class FinancialFact(db.Model):
    """One row per (account, period) value. The only source of numbers for analysis/reports."""

    __tablename__ = "financial_facts"

    id = db.Column(db.Integer, primary_key=True)
    dataset_version = db.Column(db.String(36), db.ForeignKey("dataset_versions.id"), nullable=False, index=True)
    entity_id = db.Column(db.String(36), db.ForeignKey("entities.id"), nullable=True)
    account_id = db.Column(db.String(80), db.ForeignKey("accounts.id"), nullable=False, index=True)
    period_end = db.Column(db.Date, nullable=False, index=True)
    period_type = db.Column(db.String(2), default="FY")  # FY | Q | M
    value = db.Column(db.Numeric(20, 2), nullable=False)
    currency = db.Column(db.String(3), default="INR")
    source_doc = db.Column(db.String(36), db.ForeignKey("documents.id"), nullable=True)
    source_ref = db.Column(db.JSON, nullable=True)  # {"page":3,"bbox":[...]} or {"sheet":"BS","cell":"D14"}
    confidence = db.Column(db.Float, default=1.0)
    is_derived = db.Column(db.Boolean, default=False)
