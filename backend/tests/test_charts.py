"""Chart layer: unit-aware formatting, computed takeaways, the full chart set on the seed data,
report placement, and renderer edge cases."""
import pytest

from app.agents.delivery.chart_spec import change_phrase, period_label
from app.domain.taxonomy import interleave_charts_into_sections
from app.models.report import Report
from app.orchestrator import blackboard
from app.tools.chart_render import fmt_value, render_chart
from app.utils import storage
from tests.test_detailed_analysis import completed_job  # noqa: F401 -- shared pipeline fixture

NAN = float("nan")


@pytest.mark.parametrize("value,unit,expected", [
    (0.4167, "%", "41.7%"), (1.8182, "x", "1.82x"), (67.4, "days", "67 d"), (12_000_000, "INR", "Rs 1.20 Cr"),
    (450_000, "INR", "Rs 4.5 L"), (-1_000_000, "INR", "-Rs 10.0 L"), (2_500, "INR", "Rs 2.5 K"), (NAN, "%", ""),
])
def test_fmt_value_uses_units_and_indian_scale(value, unit, expected):
    assert fmt_value(value, unit) == expected


def test_change_phrases():
    assert change_phrase("Gross margin", [0.40, 0.4167], "%") == "Gross margin 40.0% → 41.7% (+1.7 pp)"
    assert change_phrase("Current ratio", [1.82, NAN, 2.11], "x") == "Current ratio 1.82x → 2.11x (+0.29x)"
    assert change_phrase("Revenue", [1e7, 1.2e7], "INR") == "Revenue Rs 1.00 Cr → Rs 1.20 Cr (+20.0%)"
    assert change_phrase("X", [NAN], "%") == ""
    assert period_label("2024-03-31") == "Mar 2024" and period_label("2025-03-31", forecast=True) == "Mar 2025 (F)"


EXPECTED = {
    "Financial Health Scorecard": "executive_summary", "Revenue, EBITDA & EBITDA Margin": "profitability",
    "Margin Profile": "profitability", "Where Each Rupee of Income Goes": "cost_structure",
    "Liquidity Ratios vs. Benchmarks": "liquidity", "Leverage & Debt-Service Capacity": "leverage",
    "Working Capital Cycle (Days)": "working_capital", "Cash Flow Profile": "working_capital",
    "Year-over-Year Growth": "growth_returns", "Returns on Capital & Asset Efficiency": "growth_returns",
    "Revenue & Profit Outlook (with forecast range)": "forecast", "PAT Bridge — What Moved Profit": "detailed_analysis",
    "DuPont ROE Decomposition": "detailed_analysis", "Balance Sheet Structure": "detailed_analysis",
    "Bank Cash Flows by Month": "detailed_analysis", "Counterparty Concentration (share of bank flows)": "risk",
}


def test_full_chart_set_on_seed_data(app, completed_job):  # noqa: F811
    with app.app_context():
        charts = blackboard.read(completed_job.id, "charts")
    by_title = {c["title"].split(" — ")[0] if c["title"].startswith("Financial Health") else c["title"]: c
                for c in charts}
    assert set(by_title) == set(EXPECTED)
    for title, section in EXPECTED.items():
        chart = by_title[title]
        assert chart["section_key"] == section
        assert chart["takeaway"], f"{title} has no takeaway"
        assert chart["png_base64"].startswith("data:image/png;base64,")
    # no raw metric codes leak into legends/labels
    for c in charts:
        assert not any("_" in name for name in c["spec"]["series"]), c["title"]
    # the income split is on one base: every period's shares sum to 100%
    rupee = by_title["Where Each Rupee of Income Goes"]["spec"]["series"]
    for i in range(2):
        assert sum(v[i] for v in rupee.values()) == pytest.approx(1.0)
    assert "57.8%" in by_title["Where Each Rupee of Income Goes"]["takeaway"]  # 70L / (120L + 1.2L)
    # forecast uses the fiscal calendar and carries the uncertainty band
    outlook = by_title["Revenue & Profit Outlook (with forecast range)"]
    assert "by Mar 2026" in outlook["takeaway"]
    assert [p["chart_type"] for p in outlook["spec"]["panels"]] == ["band_line", "band_line"]


def test_charts_land_in_their_report_sections(app, completed_job):  # noqa: F811
    with app.app_context():
        charts = blackboard.read(completed_job.id, "charts")
        draft = blackboard.read(completed_job.id, "draft")
        sections, unassigned = interleave_charts_into_sections(draft["sections"], charts)
        report = Report.query.filter_by(dataset_version=completed_job.dataset_version_id).first()
        html = storage.resolve(report.html_uri).read_text(encoding="utf-8")
    placed = {c["chart_id"]: s["section_key"] for s in sections for c in s["charts"]}
    for c in charts:
        if c["chart_id"] in placed:
            assert placed[c["chart_id"]] == c["section_key"]
    assert len(placed) + len(unassigned) == len(charts)
    assert html.count('class="chart-image"') == len(charts)


def test_renderer_handles_edge_cases(app):
    with app.app_context():
        cases = [
            ("line", ["Mar 2024"], {"A": [0.5]}, "%", {}),
            ("bar", ["a", "b"], {"A": [NAN, 1.0], "B": [-2.0, 3.0]}, "x", {"reference_lines": [{"value": 1, "label": "L"}]}),
            ("stacked_bar", ["a", "b"], {"A": [10, 20], "B": [-5, NAN]}, "days", {"overlay": {"C": [5, 20]}}),
            ("stacked_bar_100", ["a"], {"A": [1], "B": [3]}, None, {}),
            ("waterfall", ["start", "up", "down"], {"PAT": [100, 50, -30]}, "INR", {}),
            ("hbar", ["x", "y"], {"S": [3, 5]}, "pts", {"max_values": [5, 5]}),
            ("panels", ["a", "b"], {}, None, {"panels": [
                {"title": "P1", "chart_type": "bar", "series": {"A": [1, 2]}, "unit": "x"},
                {"title": "P2", "chart_type": "band_line", "series": {"F": [1, 2]}, "unit": "INR",
                 "options": {"bands": {"F": {"lower": [0.5, 1.5], "upper": [1.5, 2.5]}}, "split_at": 0}}]}),
        ]
        for kind, labels, series, unit, opts in cases:
            out = render_chart("job_x", f"c_{kind}", kind, kind, labels, series, unit=unit, subtitle="s", options=opts)
            assert out["png_base64"].startswith("data:image/png") and out["spec"]["chart_type"] == kind
