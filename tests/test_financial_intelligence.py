"""Tests for the 40-metric Virtual CFO Financial Intelligence Engine.

Validates the 6-level drill-down reverse-flow methodology:
1. Formula & What changed
2. Governing components & Why it changed
3. Operational drivers & What caused it (Root causes)
4. What to investigate (Additional data, logs, registers)
5. What to ask management (High-impact CFO questions and action points)
"""
from __future__ import annotations

import json
from app.agents.delivery.qa import QAAgent
from app.domain.financial_intelligence import (
    TREES,
    build_cfo_diagnostic_trace,
    format_diagnostic_trace_markdown,
    get_all_diagnostic_trees,
    get_diagnostic_summary_for_category,
    resolve_metric_tree,
)
from app.domain.taxonomy import build_report_skeleton
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.job import Job
from app.utils.default_tenant import ensure_default_context
from tests.test_assistant_endpoint import _make_validated_job


def test_compendium_all_40_metrics_loaded_and_complete():
    """Verify all 40 metrics from the Virtual CFO Compendium are modeled with 6-level depth."""
    trees = get_all_diagnostic_trees()
    assert len(trees) == 40
    assert len(TREES) == 40

    ids = {t.metric_id for t in trees}
    assert ids == set(range(1, 41))

    for t in trees:
        assert t.canonical_name, f"Metric #{t.metric_id} missing canonical name"
        assert t.formula, f"Metric #{t.metric_id} ({t.canonical_name}) missing formula"
        assert t.category, f"Metric #{t.metric_id} ({t.canonical_name}) missing category"
        assert len(t.components) > 0, f"Metric #{t.metric_id} ({t.canonical_name}) has no components"
        assert len(t.key_management_questions) >= 2, f"Metric #{t.metric_id} ({t.canonical_name}) lacks management questions"
        assert len(t.investigation_checklist) >= 2, f"Metric #{t.metric_id} ({t.canonical_name}) lacks investigation checklist"


def test_metric_resolution_by_id_code_alias_and_query():
    """Verify resolution by integer ID, code, alias, and natural language question."""
    # By ID
    assert resolve_metric_tree(1).canonical_name == "Revenue Growth"
    assert resolve_metric_tree(2).canonical_name == "Gross Profit Margin"
    assert resolve_metric_tree(19).canonical_name == "Cash Conversion Cycle (CCC)"
    assert resolve_metric_tree(40).canonical_name == "Enterprise Value (EV)"

    # By exact metric code
    assert resolve_metric_tree("gross_profit_pct").metric_id == 2
    assert resolve_metric_tree("ebitda_margin").metric_id == 3
    assert resolve_metric_tree("current_ratio").metric_id == 9
    assert resolve_metric_tree("dso").metric_id == 17
    assert resolve_metric_tree("cash_conversion_cycle").metric_id == 19

    # By alias
    assert resolve_metric_tree("gpm").metric_id == 2
    assert resolve_metric_tree("quick ratio").metric_id == 10
    assert resolve_metric_tree("acid test").metric_id == 10
    assert resolve_metric_tree("d/e").metric_id == 12
    assert resolve_metric_tree("working capital").metric_id == 22
    assert resolve_metric_tree("cogs").metric_id == 27
    assert resolve_metric_tree("oee").metric_id == 32

    # By natural question
    assert resolve_metric_tree("Why did our gross profit margin drop?").metric_id == 2
    assert resolve_metric_tree("What caused the current ratio to fall?").metric_id == 9
    assert resolve_metric_tree("Explain the change in debtor days").metric_id == 17
    assert resolve_metric_tree("What to investigate for technology expense?").metric_id == 31


def test_build_cfo_diagnostic_trace_generates_reverse_flow():
    """Verify 6-level reverse-flow diagnostic trace construction."""
    trace = build_cfo_diagnostic_trace("gross_profit_pct", direction="decline")
    assert trace["found"] is True
    assert trace["metric_id"] == 2
    assert trace["canonical_name"] == "Gross Profit Margin"
    assert "COGS" in trace["formula"]
    assert trace["direction"] == "decline"
    assert len(trace["why_did_it_change"]) >= 2
    assert len(trace["what_caused_it"]) >= 3
    assert len(trace["what_to_investigate"]) >= 3
    assert len(trace["what_to_ask_management"]) >= 2

    # Check Markdown rendering
    md = format_diagnostic_trace_markdown(trace)
    assert "### Virtual CFO Diagnostic Analysis: Gross Profit Margin" in md
    assert "1. What Changed?" in md
    assert "2. Why Did It Change?" in md
    assert "3. What Caused It?" in md
    assert "4. What to Investigate" in md
    assert "5. What to Ask Management" in md


def test_qa_agent_answers_diagnostic_reverse_flow_question(client, app):
    """Verify QAAgent leverages the diagnostic engine to deliver a 5-step reverse flow answer."""
    job_id = _make_validated_job(app)
    with app.app_context():
        job = db.session.get(Job, job_id)
        agent = QAAgent(get_llm_gateway())

        # Ask a diagnostic question
        res = agent.answer(job.tenant_id, job.dataset_version_id, "Why did gross profit drop?")
        assert res["route"] in ("sql", "report_lookup")
        ans = res["answer"]

        # Must include the Virtual CFO reverse-flow structure
        assert "Virtual CFO Reverse-Flow Diagnostic" in ans or "Gross Profit" in ans
        assert "What changed" in ans
        assert "Why it changed" in ans
        assert "What caused it" in ans
        assert "What to investigate" in ans
        assert "What to ask management" in ans


def test_report_skeleton_includes_diagnostic_guidance():
    """Verify report skeleton sections are populated with diagnostic guides from the 40 metrics."""
    metrics = [
        {"metric_code": "gross_profit_pct", "value": 0.45, "unit": "%", "period_end": "2026-03-31"},
        {"metric_code": "current_ratio", "value": 1.65, "unit": "x", "period_end": "2026-03-31"},
        {"metric_code": "dso", "value": 45.0, "unit": "days", "period_end": "2026-03-31"},
    ]
    skeleton = build_report_skeleton(metrics, findings=[], health_score={"score": 85})

    profit_sec = next(s for s in skeleton if s["section_key"] == "profitability")
    assert "diagnostic_guide" in profit_sec
    assert len(profit_sec["diagnostic_guide"]) > 0
    names = [g["canonical_name"] for g in profit_sec["diagnostic_guide"]]
    assert "Gross Profit Margin" in names or "EBITDA Margin" in names
