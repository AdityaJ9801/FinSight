"""No login (this is a direct/local application, not a multi-tenant SaaS) -- every request
resolves to the same fixed default tenant/entity/user. See utils/default_tenant.py.
"""
from app.utils.default_tenant import DEFAULT_TENANT_ID, DEFAULT_USER_ID


def current_tenant_id() -> str:
    return DEFAULT_TENANT_ID


def current_user_id() -> str:
    return DEFAULT_USER_ID


def current_role() -> str:
    return "admin"
