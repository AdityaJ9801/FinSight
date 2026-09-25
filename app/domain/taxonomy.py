"""Financial taxonomy: central, authoritative mapping connecting metric codes,
analysis finding modules, chart definitions, and deterministic report sections.

Principles:
1. Deterministic first: section structure and chart placements are anchored in
   verified financial categories rather than improvised by the LLM.
2. Complete coverage: every REGISTRY metric, finding module, and chart spec
   belongs to a clear category.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CategoryDef:
    key: str
    title: str
    description: str
    metric_codes: list[str] = field(default_factory=list)
    finding_modules: list[str] = field(default_factory=list)
    chart_titles: list[str] = field(default_factory=list)
    required_topics: list[str] = field(default_factory=list)


REPORT_CATEGORIES: list[CategoryDef] = [
    CategoryDef(
        key="executive_summary",
        title="Executive Summary",
        description="High-level synthesis of financial condition, composite health score, and key takeaways.",
        metric_codes=["health_score"],
        finding_modules=[],
        chart_titles=[],
        required_topics=[
            "Overall financial health score and stability assessment",
            "Core operational strengths and critical vulnerabilities",
            "Key strategic and financial recommendations",
        ],
    ),
    CategoryDef(
        key="profitability",
        title="Profitability & Margin Analysis",
        description="Operating and net earnings power, gross margins, EBITDA, and profitability trends.",
        metric_codes=["gross_profit_pct", "ebitda", "ebitda_margin", "net_profit_margin"],
        finding_modules=["ratio"],
        chart_titles=["Profitability Margins Trend"],
        required_topics=[
            "Gross profit margin performance and cost of goods dynamics",
            "EBITDA generation and operational overhead efficiency",
            "Net profit margin (PAT) conversion and bottom-line stability",
        ],
    ),
    CategoryDef(
        key="liquidity",
        title="Liquidity & Short-Term Solvency",
        description="Working capital adequacy, liquid reserve coverage, and immediate debt-servicing ability.",
        metric_codes=["current_ratio", "quick_ratio", "cash_ratio"],
        finding_modules=["ratio"],
        chart_titles=["Liquidity Ratios Trend"],
        required_topics=[
            "Current ratio position relative to standard benchmark (1.33x - 1.50x)",
            "Acid-test / quick liquidity excluding illiquid inventory",
            "Cash and cash equivalents buffer against short-term obligations",
        ],
    ),
    CategoryDef(
        key="leverage",
        title="Leverage, Capital Structure & Debt Coverage",
        description="Gearing ratios, long-term solvency, interest obligations, and debt service capability.",
        metric_codes=["debt_to_equity", "interest_coverage", "dscr"],
        finding_modules=["ratio"],
        chart_titles=["Leverage & Interest Coverage Trend"],
        required_topics=[
            "Debt-to-equity gearing and balance sheet solvency risk",
            "Interest coverage ratio headroom over finance charges",
            "Debt service coverage ratio (DSCR) and principal repayment security",
        ],
    ),
    CategoryDef(
        key="working_capital",
        title="Working Capital & Operating Cash Cycles",
        description="Operational cash conversion cycle, receivables ageing, inventory holding, and cash flow generation.",
        metric_codes=["dso", "dio", "dpo", "cash_conversion_cycle", "ocf_to_pat", "free_cash_flow"],
        finding_modules=["cash_wc"],
        chart_titles=["Cash Conversion Cycle (Days)"],
        required_topics=[
            "Days Sales Outstanding (DSO) and customer collection efficiency",
            "Days Inventory Outstanding (DIO) and stocking turnover",
            "Days Payable Outstanding (DPO) and supplier credit terms",
            "Net Cash Conversion Cycle (CCC) and operating cash flow (OCF) conversion",
        ],
    ),
    CategoryDef(
        key="growth_returns",
        title="Growth Trends & Capital Returns",
        description="Historical revenue/profit growth rates alongside return on equity (ROE) and capital employed (ROCE).",
        metric_codes=["revenue_growth_yoy", "pat_growth_yoy", "roe", "roce", "asset_turnover"],
        finding_modules=["ratio"],
        chart_titles=["Year-over-Year Growth", "Return Ratios Trend"],
        required_topics=[
            "Top-line revenue expansion and volume/pricing trajectory",
            "Profit after tax (PAT) growth dynamics and reinvestment efficiency",
            "Return on Equity (ROE) and Return on Capital Employed (ROCE)",
            "Asset turnover and capital asset utilization efficiency",
        ],
    ),
    CategoryDef(
        key="cost_structure",
        title="Cost Structure & Expenditure Breakdown",
        description="Proportional composition of production costs, employee overheads, depreciation, and finance charges.",
        metric_codes=[],
        finding_modules=["ratio", "cash_wc"],
        chart_titles=["Cost Structure"],
        required_topics=[
            "Primary cost drivers (materials, direct labor, manufacturing costs)",
            "Fixed overhead and administrative cost absorption",
            "Operating leverage and margin sensitivity to cost inflation",
        ],
    ),
    CategoryDef(
        key="risk",
        title="Risk Assessment & Anomaly Flags",
        description="Identification of unusual transaction patterns, balance sheet anomalies, and financial red flags.",
        metric_codes=[],
        finding_modules=["risk"],
        chart_titles=[],
        required_topics=[
            "High-severity anomalies and reconciliation exceptions flagged",
            "Cash flow vs. accrual profit divergences",
            "Concentration or volatility risks requiring heightened monitoring",
        ],
    ),
    CategoryDef(
        key="gst",
        title="GST & Indirect Tax Compliance",
        description="Audit reconciliation between audited ledger turnover, GSTR-3B filings, and GSTR-2B input tax credit.",
        metric_codes=[],
        finding_modules=["gst"],
        chart_titles=[],
        required_topics=[
            "Reported ledger turnover vs. GST return turnover reconciliation",
            "Input tax credit (ITC) claims matching against supplier filings (GSTR-2B)",
            "Potential tax exposure or un-reconciled variance items",
        ],
    ),
    CategoryDef(
        key="forecast",
        title="Financial Projections & Future Outlook",
        description="Trend-based projections of future revenue and profitability under historical momentum assumptions.",
        metric_codes=["revenue_forecast", "pat_forecast"],
        finding_modules=["forecast"],
        chart_titles=["Revenue & PAT: Actual vs. Forecast"],
        required_topics=[
            "Projected revenue and PAT trajectory for future periods",
            "Underlying forecasting method and historical baseline assumptions",
            "Key sensitivities, downside risks, and covenant headroom under projections",
        ],
    ),
]

_CATEGORY_BY_KEY: dict[str, CategoryDef] = {c.key: c for c in REPORT_CATEGORIES}


def get_category_for_metric(metric_code: str) -> str | None:
    for cat in REPORT_CATEGORIES:
        if metric_code in cat.metric_codes:
            return cat.key
    return None


def get_category_for_chart(chart_title: str) -> str | None:
    chart_lower = chart_title.lower()
    for cat in REPORT_CATEGORIES:
        for t in cat.chart_titles:
            if t.lower() in chart_lower:
                return cat.key
    if "profit" in chart_lower or "margin" in chart_lower:
        return "profitability"
    if "liquid" in chart_lower or "quick" in chart_lower:
        return "liquidity"
    if "leverage" in chart_lower or "debt" in chart_lower or "coverage" in chart_lower:
        return "leverage"
    if "cash" in chart_lower or "cycle" in chart_lower or "conversion" in chart_lower:
        return "working_capital"
    if "growth" in chart_lower or "return" in chart_lower or "roe" in chart_lower:
        return "growth_returns"
    if "cost" in chart_lower or "expense" in chart_lower:
        return "cost_structure"
    if "forecast" in chart_lower or "projection" in chart_lower:
        return "forecast"
    return None


def get_category_for_finding(module: str) -> str | None:
    if module == "risk":
        return "risk"
    if module == "gst":
        return "gst"
    if module == "cash_wc":
        return "working_capital"
    if module == "forecast":
        return "forecast"
    if module == "ratio":
        return "profitability"
    return None


def build_report_skeleton(
    metrics: list[dict],
    findings: list[dict],
    health_score: dict | None = None,
    charts: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Generates the ordered, deterministic list of sections supported by available data."""
    charts = charts or []
    metric_codes = {m.get("metric_code") or m.get("code") for m in metrics if m.get("metric_code") or m.get("code")}
    finding_modules = {f.get("module") for f in findings if f.get("module")}

    chart_map: dict[str, list[str]] = {}
    for c in charts:
        cid = c.get("chart_id")
        ctitle = c.get("title", "")
        cat_key = get_category_for_chart(ctitle)
        if cat_key and cid:
            chart_map.setdefault(cat_key, []).append(cid)

    skeleton: list[dict[str, Any]] = []

    # 1. Executive Summary is always first
    skeleton.append({
        "section_key": "executive_summary",
        "heading": "Executive Summary",
        "description": _CATEGORY_BY_KEY["executive_summary"].description,
        "required_topics": _CATEGORY_BY_KEY["executive_summary"].required_topics,
        "chart_ids": chart_map.get("executive_summary", []),
    })

    # Evaluate each domain category in predefined sequence
    for cat in REPORT_CATEGORIES[1:]:
        has_metrics = bool(set(cat.metric_codes) & metric_codes)
        has_findings = bool(set(cat.finding_modules) & finding_modules)
        has_charts = bool(chart_map.get(cat.key))

        if cat.key == "risk" and "risk" not in finding_modules:
            continue
        if cat.key == "gst" and "gst" not in finding_modules:
            continue
        if cat.key == "forecast" and not (has_metrics or "forecast" in finding_modules):
            continue
        if cat.key == "cost_structure" and not has_charts:
            continue

        if has_metrics or has_findings or has_charts:
            from app.domain.financial_intelligence import get_diagnostic_summary_for_category

            skeleton.append({
                "section_key": cat.key,
                "heading": cat.title,
                "description": cat.description,
                "required_topics": cat.required_topics,
                "chart_ids": chart_map.get(cat.key, []),
                "diagnostic_guide": get_diagnostic_summary_for_category(cat.key),
            })

    return skeleton


def interleave_charts_into_sections(
    sections: list[dict[str, Any]],
    charts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Matches rendered charts to report sections by category, embedding them directly
    into the section dictionaries. Returns (enriched_sections, unassigned_charts)."""
    if not charts:
        return sections, []

    chart_by_id = {c["chart_id"]: c for c in charts if c.get("chart_id")}
    assigned_ids: set[str] = set()
    enriched_sections: list[dict[str, Any]] = []

    for sec in sections:
        sec_copy = dict(sec)
        sec_key = sec.get("section_key") or ""
        sec_heading = (sec.get("heading") or "").lower()
        sec_charts: list[dict[str, Any]] = []

        # 1. Check explicit chart_ids already on the section
        for cid in sec.get("chart_ids", []):
            if cid in chart_by_id and cid not in assigned_ids:
                sec_charts.append(chart_by_id[cid])
                assigned_ids.add(cid)

        # 2. Check title/category match for any still-unassigned charts
        for c in charts:
            cid = c.get("chart_id")
            if cid in assigned_ids:
                continue
            cat = get_category_for_chart(c.get("title", ""))
            if (cat and cat == sec_key) or (cat and cat in sec_heading):
                sec_charts.append(c)
                assigned_ids.add(cid)

        sec_copy["charts"] = sec_charts
        sec_copy["chart_ids"] = [c["chart_id"] for c in sec_charts]
        enriched_sections.append(sec_copy)

    unassigned = [c for c in charts if c.get("chart_id") not in assigned_ids]
    return enriched_sections, unassigned
