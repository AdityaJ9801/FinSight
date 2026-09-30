from datetime import datetime, timezone

from app.extensions import db
from app.utils.ids import new_id


class Tenant(db.Model):
    __tablename__ = "tenants"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("ten_"))
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    entities = db.relationship("Entity", backref="tenant", lazy="dynamic")
    users = db.relationship("User", backref="tenant", lazy="dynamic")


class Entity(db.Model):
    __tablename__ = "entities"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("ent_"))
    tenant_id = db.Column(db.String(36), db.ForeignKey("tenants.id"), nullable=False, index=True)
    legal_name = db.Column(db.String(255), nullable=False)
    gstin = db.Column(db.String(20), nullable=True)
    industry = db.Column(db.String(120), nullable=True)
    fy_start_month = db.Column(db.Integer, default=4)  # India FY default: April
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
