"""Plan templates (design doc §4.4): the orchestrator picks a template and only adjusts
parameters/optional modules, rather than letting the LLM freely design a DAG each time --
keeps job plans predictable and auditable.
"""
from __future__ import annotations

from app.agents.analysis.cash_wc import CashWorkingCapitalAgent
from app.agents.analysis.forecast import ForecastAgent
from app.agents.analysis.gst import GstComplianceAgent
from app.agents.analysis.ratio import RatioTrendAgent
from app.agents.analysis.risk import RiskAnomalyAgent

PLAN_TEMPLATES: dict[str, list] = {
    "full_analysis": [RatioTrendAgent, CashWorkingCapitalAgent, ForecastAgent, RiskAnomalyAgent, GstComplianceAgent],
    "bank_statement_review": [CashWorkingCapitalAgent, RiskAnomalyAgent],
    "gst_reconciliation": [GstComplianceAgent],
    "lender_credit_memo": [RatioTrendAgent, CashWorkingCapitalAgent, RiskAnomalyAgent, ForecastAgent],
}


def modules_for(template: str) -> list:
    return PLAN_TEMPLATES.get(template, PLAN_TEMPLATES["full_analysis"])


def is_valid_template(template: str) -> bool:
    return template in PLAN_TEMPLATES
