from datetime import datetime, timezone

from app.extensions import db
from app.utils.ids import new_id


class Account(db.Model):
    """Canonical chart of accounts, Schedule III-aligned. Global (not tenant-scoped)."""

    __tablename__ = "accounts"

    id = db.Column(db.String(80), primary_key=True)  # e.g. 'BS.CA.TRADE_RECEIVABLES'
    name = db.Column(db.String(255), nullable=False)
    statement = db.Column(db.String(4), nullable=False)  # BS | PL | CF
    parent_id = db.Column(db.String(80), db.ForeignKey("accounts.id"), nullable=True)
    normal_balance = db.Column(db.String(6), nullable=False)  # debit | credit
    coa_version = db.Column(db.String(20), default="v1")


class AccountMapping(db.Model):
    """Source row label -> canonical account. Doubles as mapping memory across jobs."""

    __tablename__ = "account_mappings"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("map_"))
    tenant_id = db.Column(db.String(36), db.ForeignKey("tenants.id"), nullable=False, index=True)
    entity_id = db.Column(db.String(36), db.ForeignKey("entities.id"), nullable=True, index=True)
    layout_id = db.Column(db.String(120), nullable=True, index=True)

    source_label = db.Column(db.String(500), nullable=False)
    source_label_norm = db.Column(db.String(500), nullable=False, index=True)
    account_id = db.Column(db.String(80), db.ForeignKey("accounts.id"), nullable=False)

    confidence = db.Column(db.Float, default=1.0)
    method = db.Column(db.String(10), default="llm")  # rule | llm | human
    approved_by = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
