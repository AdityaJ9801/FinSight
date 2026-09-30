"""Tests for the updated QAAgent, assistant delivery agent re-runs, and deterministic report redesign."""
import json
from pathlib import Path

from app.agents.delivery.qa import QAAgent
from app.agents.schemas import ReportDraftResult, ReportSection, RouteDecision
from app.domain.taxonomy import build_report_skeleton, interleave_charts_into_sections
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.finding import Finding
from app.models.job import Job
from app.models.report import Report
from app.tools.report_render import render_docx, render_html, render_pdf
from app.utils import storage
from app.utils.default_tenant import DEFAULT_ENTITY_ID, DEFAULT_TENANT_ID, ensure_default_context
from app.utils.ids import new_id
from tests.test_assistant_endpoint import _make_validated_job


def test_qa_conversational_acknowledgment_does_not_dead_end(app):
    with app.app_context():
        ensure_default_context()
        agent = QAAgent(get_llm_gateway())
        res = agent.answer("t_1", "dv_1", "ok")
        assert res["route"] == "report_lookup"
        assert "helpful" in res["answer"].lower()

        res2 = agent.answer("t_1", "dv_1", "thanks!")
        assert "helpful" in res2["answer"].lower()


def test_qa_chart_lookup_finds_and_cites_charts(client, app):
    job_id = _make_validated_job(app)
    with app.app_context():
        # Plant a mock chart in charts.json
        chart_dict = [{
            "chart_id": "chart_profit_test",
            "title": "Profitability Margins Trend",
            "caption": "EBITDA margin increased from 14% to 18% over the period.",
            "spec": {"chart_type": "line", "labels": ["FY24", "FY25"], "series": {"ebitda_margin": [0.14, 0.18]}},
            "png_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        }]
        storage.write_text(f"{job_id}/delivery/charts.json", json.dumps(chart_dict))

        job = db.session.get(Job, job_id)
        agent = QAAgent(get_llm_gateway())

        # Ask question about chart
        res = agent.answer(job.tenant_id, job.dataset_version_id, "What does the profitability chart show?")
        assert res["route"] == "chart_lookup"
        assert "Profitability Margins Trend" in res["answer"] or "chart" in res["answer"].lower()
        assert "chart_profit_test" in res["citations"] or len(res["citations"]) > 0


def test_qa_action_request_guides_user_to_assistant(app):
    with app.app_context():
        ensure_default_context()
        agent = QAAgent(get_llm_gateway())
        res = agent.answer("t_1", "dv_1", "redo the risk score excluding the one-off item")
        assert res["route"] == "action_request"
        assert "assistant" in res["answer"].lower() or "re-run" in res["answer"].lower()


def test_qa_api_endpoint_with_history(client, app):
    job_id = _make_validated_job(app)
    resp = client.post("/api/qa", json={
        "job_id": job_id,
        "question": "what is the current ratio?",
        "history": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
    })
    assert resp.status_code == 200
    data = resp.json
    assert "answer" in data
    assert data["route"] in ("sql", "report_lookup")


def test_assistant_can_re_run_report_writer_and_refreshes_report(client, app):
    job_id = _make_validated_job(app)
    with app.app_context():
        # Setup initial insights and report
        insights = {"insights": [{"title": "Strong Cash Position", "body": "Cash reserves increased."}]}
        storage.write_text(f"{job_id}/delivery/insights.json", json.dumps(insights))

    resp = client.post(f"/api/jobs/{job_id}/assistant", json={
        "chosen_agent": "report_writer",
        "action_note": "Add more detail on working capital dynamics.",
    })
    assert resp.status_code == 200
    data = resp.json
    assert data["agent_used"] == "report_writer"
    assert data["status"] in ("done", "partial")

    with app.app_context():
        job = db.session.get(Job, job_id)
        report = Report.query.filter_by(dataset_version=job.dataset_version_id).order_by(Report.created_at.desc()).first()
        assert report is not None
        assert report.html_uri is not None
        html = storage.resolve(report.html_uri).read_text(encoding="utf-8")
        assert "Executive" in html or "Report" in html


def test_taxonomy_skeleton_builder_and_chart_interleaving():
    metrics = [
        {"metric_code": "gross_profit_pct", "value": 0.45, "unit": "%", "period_end": "2026-03-31"},
        {"metric_code": "current_ratio", "value": 1.65, "unit": "x", "period_end": "2026-03-31"},
    ]
    findings = [{"module": "ratio", "title": "Gross Margin expansion", "body": "Margins expanded by 200 bps."}]
    charts = [{
        "chart_id": "c_profit",
        "title": "Profitability Margins Trend",
        "png_base64": "data:image/png;base64,abc",
        "caption": "Rising margins",
    }]

    skeleton = build_report_skeleton(metrics, findings, health_score={"score": 80, "rating": "Good"}, charts=charts)
    keys = [s["section_key"] for s in skeleton]
    assert "executive_summary" in keys
    assert "profitability" in keys
    assert "liquidity" in keys

    # Check chart interleaving
    sections = [
        {"section_key": "profitability", "heading": "Profitability & Margin Analysis", "body": "Prose about margins."},
        {"section_key": "liquidity", "heading": "Liquidity & Short-Term Solvency", "body": "Prose about liquidity."},
    ]
    enriched, unassigned = interleave_charts_into_sections(sections, charts)
    assert len(enriched[0].get("charts", [])) == 1
    assert enriched[0]["charts"][0]["chart_id"] == "c_profit"
    assert len(unassigned) == 0


def test_render_html_docx_pdf_with_executive_styling(app):
    with app.app_context():
        job_id = "test_render_job"
        sections = [
            {"heading": "Executive Summary", "body": "The company demonstrated sound performance.", "section_key": "executive_summary"},
            {
                "heading": "Profitability & Margin Analysis",
                "body": "Gross margins remained resilient.",
                "section_key": "profitability",
                "charts": [{
                    "chart_id": "c1",
                    "title": "Profitability Margins Trend",
                    "caption": "Margins over time",
                    "png_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                }],
            },
        ]
        metadata = {
            "health_score": {"score": 85, "rating": "Excellent"},
            "kpis": [{"label": "Net Margin", "value": "12.5%", "sub": "FY26"}],
        }

        html_res = render_html(job_id, "Comprehensive Financial Report", sections, charts=[], metadata=metadata)
        assert html_res["html_uri"]
        assert "Executive Performance Overview" in html_res["html"]
        assert "Excellent" in html_res["html"]

        docx_uri = render_docx(job_id, "Comprehensive Financial Report", sections, charts=[])
        assert storage.resolve(docx_uri).exists()

        pdf_uri = render_pdf(job_id, html_res["html"])
        assert storage.resolve(pdf_uri).exists()
