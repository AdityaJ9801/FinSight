from datetime import datetime, timezone

from app.extensions import db
from app.utils.ids import new_id


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.String(36), primary_key=True, default=lambda: new_id("aud_"))
    tenant_id = db.Column(db.String(36), db.ForeignKey("tenants.id"), nullable=True, index=True)
    job_id = db.Column(db.String(36), db.ForeignKey("jobs.id"), nullable=True, index=True)
    actor = db.Column(db.String(120), nullable=True)  # user id, or "system"
    action = db.Column(db.String(80), nullable=False)  # "upload", "agent_call", "tool_call", "human_correction", ...
    details = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


def log_action(action: str, tenant_id: str | None = None, job_id: str | None = None,
               actor: str | None = None, **details) -> None:
    entry = AuditLog(tenant_id=tenant_id, job_id=job_id, actor=actor or "system", action=action, details=details)
    db.session.add(entry)
    db.session.commit()
