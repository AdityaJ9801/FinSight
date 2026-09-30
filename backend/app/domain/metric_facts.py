"""Verified-figure context for chat answers.

The QA composer used to receive raw metric rows (or nothing), so answers either dumped
dicts or talked in generalities. This module picks the metrics a question is about and
pre-computes the facts an analyst would quote -- latest value, the prior period, the change
and whether that change is good -- formatted exactly as the report formats them. The model
(or the offline mock) then only has to phrase them; it never does arithmetic.
"""
from __future__ import annotations

from app.models.metric import Metric
from app.tools.report_render import format_indian_number

LABELS: dict[str, str] = {
    "current_ratio": "Current ratio", "quick_ratio": "Quick ratio", "cash_ratio": "Cash ratio",
    "debt_to_equity": "Debt to equity", "interest_coverage": "Interest coverage", "dscr": "Debt service coverage",
    "ebitda": "EBITDA", "gross_profit_pct": "Gross margin", "ebitda_margin": "EBITDA margin",
    "net_profit_margin": "Net profit margin", "roe": "Return on equity", "roce": "Return on capital employed",
    "asset_turnover": "Asset turnover", "dso": "Receivable days", "dio": "Inventory days", "dpo": "Payable days",
    "cash_conversion_cycle": "Cash conversion cycle", "revenue_growth_yoy": "Revenue growth",
    "pat_growth_yoy": "PAT growth", "ocf_to_pat": "Operating cash flow to PAT", "free_cash_flow": "Free cash flow",
    "revenue_forecast": "Revenue forecast", "pat_forecast": "PAT forecast", "risk_score": "Risk score",
    "health_score": "Health score",
    "ebit": "EBIT", "working_capital": "Working capital", "net_debt": "Net debt",
    "net_debt_to_ebitda": "Net debt to EBITDA", "equity_multiplier": "Equity multiplier",
    "cogs_to_revenue": "Materials cost to revenue", "employee_cost_to_revenue": "Employee cost to revenue",
    "other_expenses_to_revenue": "Other expenses to revenue", "finance_cost_to_revenue": "Finance cost to revenue",
    "ebitda_growth_yoy": "EBITDA growth", "revenue_cagr": "Revenue growth per year", "ebitda_cagr": "EBITDA growth per year",
    "pat_cagr": "PAT growth per year", "total_assets_cagr": "Asset growth per year",
    "net_cash_after_investing": "Net cash after investing",
    "bank_inflows": "Monthly bank inflows", "bank_outflows": "Monthly bank outflows",
    "bank_net_flow": "Monthly net cash flow", "bank_closing_balance": "Closing bank balance",
    "bank_avg_monthly_inflow": "Average monthly inflow", "bank_avg_monthly_outflow": "Average monthly outflow",
    "bank_min_balance": "Lowest bank balance", "bank_cash_cover_months": "Cash cover",
    "bank_top_payer_share": "Largest payer's share of receipts", "bank_negative_month_share": "Share of cash-negative months",
}

LOWER_IS_BETTER = {"debt_to_equity", "dso", "dio", "cash_conversion_cycle", "risk_score",
                   "net_debt", "net_debt_to_ebitda", "equity_multiplier", "cogs_to_revenue",
                   "employee_cost_to_revenue", "other_expenses_to_revenue", "finance_cost_to_revenue",
                   "bank_outflows", "bank_avg_monthly_outflow", "bank_top_payer_share", "bank_negative_month_share"}

# Question phrases -> metrics. Specific names first; broad topics expand to a small set.
_SYNONYMS: list[tuple[tuple[str, ...], list[str]]] = [
    (("ebitda margin", "operating margin"), ["ebitda_margin"]),
    (("gross margin", "gross profit"), ["gross_profit_pct"]),
    (("net margin", "net profit", "pat margin", "profit margin"), ["net_profit_margin"]),
    (("ebitda",), ["ebitda", "ebitda_margin"]),
    (("current ratio",), ["current_ratio"]),
    (("quick ratio", "acid"), ["quick_ratio"]),
    (("debt to equity", "debt-to-equity", "d/e", "gearing"), ["debt_to_equity"]),
    (("interest coverage", "icr"), ["interest_coverage"]),
    (("dscr", "debt service"), ["dscr"]),
    (("roe", "return on equity"), ["roe"]),
    (("roce", "return on capital"), ["roce"]),
    (("receivable", "debtor", "dso", "collection"), ["dso"]),
    (("inventory", "stock days", "dio"), ["dio"]),
    (("payable", "creditor", "dpo"), ["dpo"]),
    (("cash conversion cycle", "ccc"), ["cash_conversion_cycle"]),
    (("free cash flow", "fcf"), ["free_cash_flow"]),
    (("revenue growth", "sales growth", "top line", "top-line"), ["revenue_growth_yoy"]),
    (("pat growth", "profit growth", "earnings growth"), ["pat_growth_yoy"]),
    (("forecast", "projection", "next year"), ["revenue_forecast", "pat_forecast"]),
    (("risk",), ["risk_score"]),
    (("health",), ["health_score"]),
    (("runway", "cash cover", "months of cash"), ["bank_cash_cover_months", "bank_avg_monthly_outflow"]),
    (("closing balance", "bank balance"), ["bank_closing_balance", "bank_min_balance"]),
    (("concentration", "largest customer", "top customer", "payer"), ["bank_top_payer_share"]),
    (("burn", "outflow"), ["bank_avg_monthly_outflow", "bank_outflows"]),
    (("inflow", "receipts"), ["bank_avg_monthly_inflow", "bank_inflows"]),
    (("working capital",), ["dso", "dio", "dpo", "cash_conversion_cycle"]),
    (("liquidity", "short-term", "short term"), ["current_ratio", "quick_ratio", "cash_ratio"]),
    (("leverage", "debt", "solvency", "borrowing"), ["debt_to_equity", "interest_coverage", "dscr"]),
    (("profitab", "margin"), ["gross_profit_pct", "ebitda_margin", "net_profit_margin"]),
    (("return",), ["roe", "roce"]),
    (("growth",), ["revenue_growth_yoy", "pat_growth_yoy"]),
    (("cash flow", "cash position", "cash"), ["free_cash_flow", "ocf_to_pat", "bank_closing_balance",
                                               "bank_cash_cover_months", "bank_net_flow"]),
    (("lender", "credit", "bank loan", "covenant"), ["debt_to_equity", "interest_coverage", "dscr", "current_ratio",
                                                     "risk_score", "bank_cash_cover_months"]),
    (("overall", "summary", "summarise", "summarize", "overview", "how is the company", "how healthy"),
     ["health_score", "ebitda_margin", "net_profit_margin", "current_ratio", "debt_to_equity", "revenue_growth_yoy",
      "bank_closing_balance", "bank_cash_cover_months"]),
]


def match_metrics(question: str) -> list[str]:
    low = f" {question.lower()} "
    codes: list[str] = []
    for phrases, targets in _SYNONYMS:
        if any(p in low for p in phrases):
            codes += [c for c in targets if c not in codes]
            if len(codes) >= 8:
                break
    return codes


def _change_display(unit: str, prev: float, cur: float) -> str:
    d = cur - prev
    sign = "+" if d >= 0 else "-"
    if unit == "%":
        return f"{sign}{abs(d) * 100:.1f} pts"
    if unit == "x":
        return f"{sign}{abs(d):.2f}x"
    if unit == "days":
        return f"{sign}{abs(d):.0f} days"
    if unit == "months":
        return f"{sign}{abs(d):.1f} months"
    if prev:
        return f"{sign}{abs(d) / abs(prev) * 100:.1f}%"
    return f"{sign}{format_indian_number(abs(d), unit)}"


def build_facts(dataset_version_id: str, codes: list[str]) -> list[dict]:
    """One entry per requested metric that has data: its latest value and, when there is a
    prior period, the change and whether it moved in the healthy direction."""
    if not codes:
        return []
    rows = (Metric.query.filter(Metric.dataset_version == dataset_version_id, Metric.metric_code.in_(codes))
            .order_by(Metric.period_end).all())
    series: dict[str, list[Metric]] = {}
    for r in rows:
        if r.value is not None:
            series.setdefault(r.metric_code, []).append(r)
    facts = []
    for code in codes:
        points = series.get(code)
        if not points:
            continue
        cur = points[-1]
        fact = {
            "metric_code": code, "metric": LABELS.get(code, code.replace("_", " ")),
            "period": cur.period_end.isoformat(), "value": float(cur.value), "unit": cur.unit,
            "display": format_indian_number(float(cur.value), cur.unit),
        }
        if len(points) > 1:
            prev = points[-2]
            pv, cv = float(prev.value), float(cur.value)
            improved = None if pv == cv else ((cv < pv) if code in LOWER_IS_BETTER else (cv > pv))
            fact.update({
                "prior_period": prev.period_end.isoformat(),
                "prior_display": format_indian_number(pv, prev.unit),
                "change_display": _change_display(cur.unit, pv, cv),
                "direction": "up" if cv > pv else "down" if cv < pv else "flat",
                "improved": improved,
            })
        facts.append(fact)
    return facts
