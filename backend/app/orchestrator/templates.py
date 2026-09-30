"""Plan templates (design doc §4.4): the orchestrator picks a template and only adjusts
parameters/optional modules, rather than letting the LLM freely design a DAG each time --
keeps job plans predictable and auditable. Templates name agents; the classes come from the
agent registry (app/agents/registry.py).
"""
from __future__ import annotations

from app.agents import registry

PLAN_TEMPLATES: dict[str, list[str]] = {
    "full_analysis": ["ratio", "cash_wc", "forecast", "risk", "gst", "detailed_analytics"],
    "bank_statement_review": ["cash_wc", "risk", "detailed_analytics"],
    "gst_reconciliation": ["gst"],
    "lender_credit_memo": ["ratio", "cash_wc", "risk", "forecast", "detailed_analytics"],
}


def module_names_for(template: str) -> list[str]:
    return PLAN_TEMPLATES.get(template, PLAN_TEMPLATES["full_analysis"])


def modules_for(template: str) -> list:
    return [registry.get(name).load() for name in module_names_for(template)]


def is_valid_template(template: str) -> bool:
    return template in PLAN_TEMPLATES
