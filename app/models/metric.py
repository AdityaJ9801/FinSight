from app.extensions import db


class Metric(db.Model):
    """The ONLY source of numbers allowed in reports (§6.7). Report placeholders resolve against this."""

    __tablename__ = "metrics"

    id = db.Column(db.String(80), primary_key=True)  # 'm_current_ratio_FY24'
    dataset_version = db.Column(db.String(36), db.ForeignKey("dataset_versions.id"), nullable=False, index=True)
    metric_code = db.Column(db.String(60), nullable=False, index=True)
    period_end = db.Column(db.Date, nullable=False)
    value = db.Column(db.Numeric(20, 4), nullable=True)
    unit = db.Column(db.String(20), nullable=True)
    formula_version = db.Column(db.String(20), default="1.0")
    inputs = db.Column(db.JSON, nullable=True)  # fact ids used
