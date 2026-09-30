"""Metric registry: formulas as versioned, unit-tested code (design doc §6.6). LLM agents
call `metrics.compute` and interpret the results; they never compute numbers themselves.
Formulas read from a flat {account_id: value} dict for one period (or two, for YoY-style
metrics) -- never from raw documents.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from app.tools.registry import tool


def safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


@dataclass
class MetricDef:
    code: str
    version: str
    unit: str
    inputs: list[str]
    group: str
    func: Callable
    periods_needed: int = 1


REGISTRY: dict[str, MetricDef] = {}


def metric(code: str, version: str, unit: str, inputs: list[str], group: str, periods_needed: int = 1):
    def decorator(func: Callable) -> Callable:
        REGISTRY[code] = MetricDef(code, version, unit, inputs, group, func, periods_needed)
        return func

    return decorator


# --- Liquidity ---

@metric("current_ratio", "1.0", "x", ["BS.CA.TOTAL", "BS.CL.TOTAL"], "ratio")
def current_ratio(f):
    return safe_div(f["BS.CA.TOTAL"], f["BS.CL.TOTAL"])


@metric("quick_ratio", "1.0", "x", ["BS.CA.TOTAL", "BS.CA.INVENTORY", "BS.CL.TOTAL"], "ratio")
def quick_ratio(f):
    return safe_div(f["BS.CA.TOTAL"] - f["BS.CA.INVENTORY"], f["BS.CL.TOTAL"])


@metric("cash_ratio", "1.0", "x", ["BS.CA.CASH", "BS.CL.TOTAL"], "ratio")
def cash_ratio(f):
    return safe_div(f["BS.CA.CASH"], f["BS.CL.TOTAL"])


# --- Leverage ---

@metric("debt_to_equity", "1.0", "x",
        ["BS.CL.SHORT_TERM_BORROWINGS", "BS.NCL.LONG_TERM_BORROWINGS", "BS.EQ.TOTAL"], "ratio")
def debt_to_equity(f):
    debt = f["BS.CL.SHORT_TERM_BORROWINGS"] + f["BS.NCL.LONG_TERM_BORROWINGS"]
    return safe_div(debt, f["BS.EQ.TOTAL"])


def operating_expenses(f) -> float:
    """Expenses before depreciation and finance costs. Uses the statement's own total
    expenses when reported (so no expense caption is missed); otherwise every expense line,
    including purchases of stock-in-trade and changes in inventories, net of expenditure
    transferred to capital -- EBITDA previously ignored those three and overstated profit."""
    if "PL.TOTAL_EXPENSES" in f:
        return f["PL.TOTAL_EXPENSES"] - f.get("PL.DEPRECIATION", 0.0) - f.get("PL.FINANCE_COST", 0.0)
    return (f["PL.COGS"] + f.get("PL.PURCHASES_STOCK_IN_TRADE", 0.0) + f.get("PL.CHANGES_IN_INVENTORY", 0.0)
            + f["PL.EMPLOYEE_COST"] + f["PL.OTHER_EXPENSES"] - f.get("PL.EXPENSES_CAPITALISED", 0.0))


def _ebitda(f) -> float:
    return f["PL.REVENUE"] + f["PL.OTHER_INCOME"] - operating_expenses(f)


@metric("ebitda", "1.0", "INR",
        ["PL.REVENUE", "PL.OTHER_INCOME", "PL.COGS", "PL.EMPLOYEE_COST", "PL.OTHER_EXPENSES"], "ratio")
def ebitda(f):
    return _ebitda(f)


@metric("interest_coverage", "1.0", "x",
        ["PL.REVENUE", "PL.OTHER_INCOME", "PL.COGS", "PL.EMPLOYEE_COST", "PL.OTHER_EXPENSES", "PL.FINANCE_COST"],
        "ratio")
def interest_coverage(f):
    return safe_div(_ebitda(f), f["PL.FINANCE_COST"])


@metric("dscr", "1.0", "x",
        ["PL.PBT", "PL.FINANCE_COST", "PL.DEPRECIATION", "BS.NCL.LONG_TERM_BORROWINGS"], "ratio")
def dscr(f):
    # Simplified DSCR: (PBT + interest + depreciation) / (interest + a proxy for principal
    # repayment). Without an amortization schedule we can't know principal due this period,
    # so we use finance cost alone as the debt-service proxy -- documented simplification.
    numerator = f["PL.PBT"] + f["PL.FINANCE_COST"] + f["PL.DEPRECIATION"]
    return safe_div(numerator, f["PL.FINANCE_COST"])


# --- Profitability ---

@metric("gross_profit_pct", "1.0", "%", ["PL.REVENUE", "PL.COGS"], "ratio")
def gross_profit_pct(f):
    # cost of goods sold = materials consumed + purchases of stock-in-trade + change in inventories
    cogs = f["PL.COGS"] + f.get("PL.PURCHASES_STOCK_IN_TRADE", 0.0) + f.get("PL.CHANGES_IN_INVENTORY", 0.0)
    return safe_div(f["PL.REVENUE"] - cogs, f["PL.REVENUE"])


@metric("ebitda_margin", "1.0", "%",
        ["PL.REVENUE", "PL.OTHER_INCOME", "PL.COGS", "PL.EMPLOYEE_COST", "PL.OTHER_EXPENSES"], "ratio")
def ebitda_margin(f):
    return safe_div(_ebitda(f), f["PL.REVENUE"])


@metric("net_profit_margin", "1.0", "%", ["PL.PAT", "PL.REVENUE"], "ratio")
def net_profit_margin(f):
    return safe_div(f["PL.PAT"], f["PL.REVENUE"])


@metric("roe", "1.0", "%", ["PL.PAT", "BS.EQ.TOTAL"], "ratio")
def roe(f):
    return safe_div(f["PL.PAT"], f["BS.EQ.TOTAL"])


@metric("roce", "1.0", "%",
        ["PL.PBT", "PL.FINANCE_COST", "BS.EQ.TOTAL", "BS.NCL.LONG_TERM_BORROWINGS"], "ratio")
def roce(f):
    capital_employed = f["BS.EQ.TOTAL"] + f["BS.NCL.LONG_TERM_BORROWINGS"]
    return safe_div(f["PL.PBT"] + f["PL.FINANCE_COST"], capital_employed)


# --- Efficiency ---

@metric("dso", "1.0", "days", ["BS.CA.TRADE_RECEIVABLES", "PL.REVENUE"], "cash_wc")
def dso(f):
    ratio = safe_div(f["BS.CA.TRADE_RECEIVABLES"], f["PL.REVENUE"])
    return ratio * 365 if ratio is not None else None


@metric("dio", "1.0", "days", ["BS.CA.INVENTORY", "PL.COGS"], "cash_wc")
def dio(f):
    ratio = safe_div(f["BS.CA.INVENTORY"], f["PL.COGS"])
    return ratio * 365 if ratio is not None else None


@metric("dpo", "1.0", "days", ["BS.CL.TRADE_PAYABLES", "PL.COGS"], "cash_wc")
def dpo(f):
    ratio = safe_div(f["BS.CL.TRADE_PAYABLES"], f["PL.COGS"])
    return ratio * 365 if ratio is not None else None


@metric("cash_conversion_cycle", "1.0", "days",
        ["BS.CA.TRADE_RECEIVABLES", "PL.REVENUE", "BS.CA.INVENTORY", "PL.COGS", "BS.CL.TRADE_PAYABLES"],
        "cash_wc")
def cash_conversion_cycle(f):
    d_so = dso(f)
    d_io = dio(f)
    d_po = dpo(f)
    if None in (d_so, d_io, d_po):
        return None
    return d_so + d_io - d_po


@metric("asset_turnover", "1.0", "x", ["PL.REVENUE", "BS.TOTAL_ASSETS"], "ratio")
def asset_turnover(f):
    return safe_div(f["PL.REVENUE"], f["BS.TOTAL_ASSETS"])


# --- Growth (needs current + prior period) ---

@metric("revenue_growth_yoy", "1.0", "%", ["PL.REVENUE"], "ratio", periods_needed=2)
def revenue_growth_yoy(f_curr, f_prev):
    return safe_div(f_curr["PL.REVENUE"] - f_prev["PL.REVENUE"], f_prev["PL.REVENUE"])


@metric("pat_growth_yoy", "1.0", "%", ["PL.PAT"], "ratio", periods_needed=2)
def pat_growth_yoy(f_curr, f_prev):
    return safe_div(f_curr["PL.PAT"] - f_prev["PL.PAT"], abs(f_prev["PL.PAT"]) if f_prev["PL.PAT"] else None)


# --- Cash ---

@metric("ocf_to_pat", "1.0", "x", ["CF.OPERATING", "PL.PAT"], "cash_wc")
def ocf_to_pat(f):
    return safe_div(f["CF.OPERATING"], f["PL.PAT"])


@metric("free_cash_flow", "2.0", "INR", ["CF.OPERATING", "CF.CAPEX"], "cash_wc")
def free_cash_flow(f):
    # Standard FCF: operating cash flow less capital expenditure. v1.0 was OCF + total
    # investing cash flow, which treated purchases of subsidiaries / financial investments
    # as capex (a real filing showed FCF of -10,726 crore where OCF - capex was +12,400).
    # Capex is presented as an outflow (negative); abs() accepts either presentation.
    return f["CF.OPERATING"] - abs(f["CF.CAPEX"])


@metric("net_cash_after_investing", "1.0", "INR", ["CF.OPERATING", "CF.INVESTING"], "cash_wc")
def net_cash_after_investing(f):
    # Post-investment net cash flow: OCF + ALL investing cash flows (incl. acquisitions and
    # financial investments). Kept, under its own name, because lenders do look at it --
    # it is not free cash flow and must not be labelled as such.
    return f["CF.OPERATING"] + f["CF.INVESTING"]


# --- Detailed statement analysis (detailed_analytics group) ---

@metric("ebit", "1.0", "INR",
        ["PL.REVENUE", "PL.OTHER_INCOME", "PL.COGS", "PL.EMPLOYEE_COST", "PL.OTHER_EXPENSES", "PL.DEPRECIATION"],
        "detailed_analytics")
def ebit(f):
    return _ebitda(f) - f["PL.DEPRECIATION"]


@metric("equity_multiplier", "1.0", "x", ["BS.TOTAL_ASSETS", "BS.EQ.TOTAL"], "detailed_analytics")
def equity_multiplier(f):
    return safe_div(f["BS.TOTAL_ASSETS"], f["BS.EQ.TOTAL"])


@metric("cogs_to_revenue", "1.0", "%", ["PL.COGS", "PL.REVENUE"], "detailed_analytics")
def cogs_to_revenue(f):
    return safe_div(f["PL.COGS"], f["PL.REVENUE"])


@metric("employee_cost_to_revenue", "1.0", "%", ["PL.EMPLOYEE_COST", "PL.REVENUE"], "detailed_analytics")
def employee_cost_to_revenue(f):
    return safe_div(f["PL.EMPLOYEE_COST"], f["PL.REVENUE"])


@metric("other_expenses_to_revenue", "1.0", "%", ["PL.OTHER_EXPENSES", "PL.REVENUE"], "detailed_analytics")
def other_expenses_to_revenue(f):
    return safe_div(f["PL.OTHER_EXPENSES"], f["PL.REVENUE"])


@metric("finance_cost_to_revenue", "1.0", "%", ["PL.FINANCE_COST", "PL.REVENUE"], "detailed_analytics")
def finance_cost_to_revenue(f):
    return safe_div(f["PL.FINANCE_COST"], f["PL.REVENUE"])


@metric("working_capital", "1.0", "INR", ["BS.CA.TOTAL", "BS.CL.TOTAL"], "detailed_analytics")
def working_capital(f):
    return f["BS.CA.TOTAL"] - f["BS.CL.TOTAL"]


@metric("net_debt", "1.0", "INR",
        ["BS.CL.SHORT_TERM_BORROWINGS", "BS.NCL.LONG_TERM_BORROWINGS", "BS.CA.CASH"], "detailed_analytics")
def net_debt(f):
    return f["BS.CL.SHORT_TERM_BORROWINGS"] + f["BS.NCL.LONG_TERM_BORROWINGS"] - f["BS.CA.CASH"]


@metric("net_debt_to_ebitda", "1.0", "x",
        ["BS.CL.SHORT_TERM_BORROWINGS", "BS.NCL.LONG_TERM_BORROWINGS", "BS.CA.CASH",
         "PL.REVENUE", "PL.OTHER_INCOME", "PL.COGS", "PL.EMPLOYEE_COST", "PL.OTHER_EXPENSES"], "detailed_analytics")
def net_debt_to_ebitda(f):
    return safe_div(net_debt(f), _ebitda(f))


@metric("ebitda_growth_yoy", "1.0", "%",
        ["PL.REVENUE", "PL.OTHER_INCOME", "PL.COGS", "PL.EMPLOYEE_COST", "PL.OTHER_EXPENSES"], "detailed_analytics",
        periods_needed=2)
def ebitda_growth_yoy(f_curr, f_prev):
    prev = _ebitda(f_prev)
    return safe_div(_ebitda(f_curr) - prev, abs(prev) if prev else None)


def compute_all(facts_by_period: dict[date, dict[str, float]]) -> list[dict]:
    """facts_by_period: {period_end: {account_id: value}}. Returns metric result dicts
    ready to persist to the `metrics` table."""
    periods_sorted = sorted(facts_by_period.keys())
    results = []
    for i, period in enumerate(periods_sorted):
        f = facts_by_period[period]
        for md in REGISTRY.values():
            try:
                if md.periods_needed == 1:
                    if not all(k in f for k in md.inputs):
                        continue
                    value = md.func(f)
                else:
                    if i == 0:
                        continue
                    f_prev = facts_by_period[periods_sorted[i - 1]]
                    if not all(k in f for k in md.inputs) or not all(k in f_prev for k in md.inputs):
                        continue
                    value = md.func(f, f_prev)
            except (KeyError, ZeroDivisionError, TypeError):
                continue
            if value is None:
                continue
            results.append({
                "metric_code": md.code, "period_end": period, "value": value,
                "unit": md.unit, "formula_version": md.version, "inputs": md.inputs, "group": md.group,
            })
    return results


tool("metrics.compute", allowed_agents=["ratio", "cash_wc", "forecast", "risk", "gst", "detailed_analytics",
                                        "insight_reasoner"])(compute_all)


def metric_row_id(dataset_version_id: str, metric_code: str, period_end: date) -> str:
    """Metric primary keys are scoped by dataset version. They used to be just
    m_<code>_<period>, so a second job covering the same periods looked up the first job's
    row by id and re-pointed it at itself -- silently breaking the first job's placeholders,
    charts and Q&A (and racing when two jobs ran concurrently)."""
    return f"m_{dataset_version_id}_{metric_code}_{period_end.isoformat()}"


def persist_metrics(dataset_version_id: str, metric_dicts: list[dict]) -> list:
    from app.extensions import db
    from app.models.metric import Metric

    saved = []
    for m in metric_dicts:
        metric_id = metric_row_id(dataset_version_id, m["metric_code"], m["period_end"])
        row = db.session.get(Metric, metric_id) or Metric(id=metric_id, dataset_version=dataset_version_id)
        row.dataset_version = dataset_version_id
        row.metric_code = m["metric_code"]
        row.period_end = m["period_end"]
        row.value = m["value"]
        row.unit = m["unit"]
        row.formula_version = m["formula_version"]
        row.inputs = m["inputs"]
        db.session.add(row)
        saved.append(row)
    db.session.commit()
    return saved
