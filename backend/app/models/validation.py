from app.extensions import db


class ValidationResult(db.Model):
    __tablename__ = "validation_results"

    id = db.Column(db.Integer, primary_key=True)
    dataset_version = db.Column(db.String(36), db.ForeignKey("dataset_versions.id"), nullable=False, index=True)
    check_code = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(10), nullable=False)  # pass | fail | warn
    expected = db.Column(db.Numeric(20, 2), nullable=True)
    actual = db.Column(db.Numeric(20, 2), nullable=True)
    diff = db.Column(db.Numeric(20, 2), nullable=True)
    details = db.Column(db.JSON, nullable=True)
