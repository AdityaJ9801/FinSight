from datetime import datetime, timezone

from app.extensions import db
from app.utils.ids import new_id


class ReviewItem(db.Model):
    __tablename__ = "review_items"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("rev_"))
    job_id = db.Column(db.String(36), db.ForeignKey("jobs.id"), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)  # mapping | extraction | reconciliation
    payload = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(20), default="open")  # open | resolved
    resolved_by = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    resolution = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime, nullable=True)
