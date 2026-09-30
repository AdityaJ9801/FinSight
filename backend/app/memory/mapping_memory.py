"""Approved-mapping memory (design doc §6.8 "entity knowledge" tier): once a human or a
confident LLM/rule mapping is approved for a tenant/layout, the same source label maps
automatically next time -- no repeat LLM calls for repeat layouts (design doc §2 principle
3, §11 cost control).
"""
from __future__ import annotations

from app.domain.coa import normalize_label
from app.extensions import db
from app.models.account import Account, AccountMapping
from app.tools.registry import tool


def lookup_memory(tenant_id: str, layout_id: str | None, label: str) -> AccountMapping | None:
    norm = normalize_label(label)
    query = AccountMapping.query.filter_by(tenant_id=tenant_id, source_label_norm=norm)
    if layout_id:
        by_layout = query.filter_by(layout_id=layout_id).order_by(AccountMapping.created_at.desc()).first()
        if by_layout:
            return by_layout
    return query.order_by(AccountMapping.created_at.desc()).first()


def write_memory(tenant_id: str, entity_id: str | None, layout_id: str | None, label: str,
                  account_id: str, confidence: float, method: str, approved_by: str | None = None) -> AccountMapping:
    mapping = AccountMapping(
        tenant_id=tenant_id, entity_id=entity_id, layout_id=layout_id,
        source_label=label, source_label_norm=normalize_label(label),
        account_id=account_id, confidence=confidence, method=method, approved_by=approved_by,
    )
    db.session.add(mapping)
    db.session.commit()
    return mapping


def coa_lookup(query: str | None = None) -> list[dict]:
    q = Account.query
    if query:
        q = q.filter(Account.name.ilike(f"%{query}%"))
    return [{"id": a.id, "name": a.name, "statement": a.statement} for a in q.all()]


tool("coa.lookup", allowed_agents=["schema_mapper"])(coa_lookup)
tool("mapping.memory", allowed_agents=["schema_mapper"])(lookup_memory)
