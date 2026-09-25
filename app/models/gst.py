from app.extensions import db


class GstReturn(db.Model):
    __tablename__ = "gst_returns"

    id = db.Column(db.Integer, primary_key=True)
    dataset_version = db.Column(db.String(36), db.ForeignKey("dataset_versions.id"), nullable=False, index=True)
    return_type = db.Column(db.String(10), nullable=False)  # GSTR1 | GSTR3B | GSTR2B
    period = db.Column(db.Date, nullable=False)
    field = db.Column(db.String(120), nullable=False)
    value = db.Column(db.Numeric(20, 2), nullable=False)
    source_doc = db.Column(db.String(36), db.ForeignKey("documents.id"), nullable=True)
    source_ref = db.Column(db.JSON, nullable=True)
