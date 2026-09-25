from app.extensions import db


class BankTransaction(db.Model):
    __tablename__ = "bank_transactions"

    id = db.Column(db.Integer, primary_key=True)
    dataset_version = db.Column(db.String(36), db.ForeignKey("dataset_versions.id"), nullable=False, index=True)
    account_no_masked = db.Column(db.String(40), nullable=True)
    txn_date = db.Column(db.Date, nullable=False, index=True)
    narration = db.Column(db.String(500), nullable=True)
    debit = db.Column(db.Numeric(20, 2), default=0)
    credit = db.Column(db.Numeric(20, 2), default=0)
    balance = db.Column(db.Numeric(20, 2), nullable=True)
    category = db.Column(db.String(60), nullable=True)
    counterparty = db.Column(db.String(255), nullable=True)
    source_doc = db.Column(db.String(36), db.ForeignKey("documents.id"), nullable=True)
    source_ref = db.Column(db.JSON, nullable=True)
