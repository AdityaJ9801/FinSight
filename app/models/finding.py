from app.extensions import db
from app.utils.ids import new_id


class Finding(db.Model):
    __tablename__ = "findings"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("fnd_"))
    dataset_version = db.Column(db.String(36), db.ForeignKey("dataset_versions.id"), nullable=False, index=True)
    module = db.Column(db.String(40), nullable=False)  # ratio | cash_wc | forecast | risk | gst
    severity = db.Column(db.String(10), default="info")  # info | warn | error
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    metric_ids = db.Column(db.JSON, default=list)
    confidence = db.Column(db.Float, default=1.0)
