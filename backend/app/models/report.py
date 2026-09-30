from datetime import datetime, timezone

from app.extensions import db
from app.utils.ids import new_id


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("rep_"))
    dataset_version = db.Column(db.String(36), db.ForeignKey("dataset_versions.id"), nullable=False, index=True)
    template = db.Column(db.String(60), default="full_analysis")
    draft_uri = db.Column(db.String(500), nullable=True)
    html_uri = db.Column(db.String(500), nullable=True)
    docx_uri = db.Column(db.String(500), nullable=True)
    pdf_uri = db.Column(db.String(500), nullable=True)
    verifier_status = db.Column(db.String(20), default="pending")  # pending|pass|failed
    revision = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
