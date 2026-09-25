"""Single-tenant "direct application" mode: no login, no multi-tenant routing -- every API
call operates under one fixed tenant/entity/user, created automatically by `flask init-db`
(idempotent, safe to call again). Fixed (not randomly generated) ids so every part of the
app can reference them without a lookup or without the app having handled a request yet.

The tenant_id/entity_id columns throughout the schema are kept (ripping them out would be
a much larger, riskier change for what's fundamentally a UX simplification, not a data
model change) -- they just always resolve to these same three rows now instead of varying
per logged-in user.
"""
from __future__ import annotations

DEFAULT_TENANT_ID = "ten_default"
DEFAULT_ENTITY_ID = "ent_default"
DEFAULT_USER_ID = "usr_default"


def ensure_default_context() -> None:
    from app.extensions import db
    from app.models.tenant import Entity, Tenant
    from app.models.user import User

    if db.session.get(Tenant, DEFAULT_TENANT_ID) is None:
        db.session.add(Tenant(id=DEFAULT_TENANT_ID, name="Default"))
    if db.session.get(Entity, DEFAULT_ENTITY_ID) is None:
        db.session.add(Entity(id=DEFAULT_ENTITY_ID, tenant_id=DEFAULT_TENANT_ID, legal_name="Default Entity"))
    if db.session.get(User, DEFAULT_USER_ID) is None:
        user = User(id=DEFAULT_USER_ID, tenant_id=DEFAULT_TENANT_ID, email="local@finsight.local", role="admin")
        user.set_password(DEFAULT_USER_ID)  # column is NOT NULL; the value is never checked -- there's no login
        db.session.add(user)
    db.session.commit()
