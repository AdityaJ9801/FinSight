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


def _ebitda(f) -> float:
    return f["PL.REVENUE"] + f["PL.OTHER_INCOME"] - f["PL.COGS"] - f["PL.EMPLOYEE_COST"] - f["PL.OTHER_EXPENSES"]


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
    return safe_div(f["PL.REVENUE"] - f["PL.COGS"], f["PL.REVENUE"])


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


@metric("free_cash_flow", "1.0", "INR", ["CF.OPERATING", "CF.INVESTING"], "cash_wc")
def free_cash_flow(f):
    # Approximation: operating cash flow net of investing outflow, in the absence of a
    # dedicated capex line item in the canonical CoA.
    return f["CF.OPERATING"] + f["CF.INVESTING"]


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


tool("metrics.compute", allowed_agents=["ratio", "cash_wc", "forecast", "risk", "gst", "insight_reasoner"])(compute_all)


def persist_metrics(dataset_version_id: str, metric_dicts: list[dict]) -> list:
    from app.extensions import db
    from app.models.metric import Metric

    saved = []
    for m in metric_dicts:
        metric_id = f"m_{m['metric_code']}_{m['period_end'].isoformat()}"
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
