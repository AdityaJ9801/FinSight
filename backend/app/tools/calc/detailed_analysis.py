"""Detailed financial-statement analysis -- the deterministic engine behind the report's
"Detailed Statement Analysis" tables and the profit-bridge / DuPont / balance-sheet / bank
charts. Every figure is computed in code from the validated ledger, never by an LLM.

Analyses:
- horizontal (trend) analysis: every statement line by period, absolute and % change
- vertical (common-size) analysis: P&L lines as % of revenue, balance sheet as % of total assets
- DuPont decomposition: ROE = net margin x asset turnover x equity multiplier
- growth: CAGR of revenue, EBITDA, PAT and total assets over the full history
- profit bridge: what moved PAT from the prior period to the latest one, line by line
- leverage & liquidity: working capital, net debt, net debt / EBITDA
- bank analytics: monthly inflows/outflows/net flow and top counterparties
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.domain.coa import CANONICAL_ACCOUNTS
from app.domain.validation_rules import EXPENSE_LINES, exceptional_effect
from app.tools.calc.metrics import _ebitda, safe_div
from app.tools.registry import tool

ACCOUNT_NAMES = {acc_id: name for acc_id, name, _, _, _ in CANONICAL_ACCOUNTS}
ACCOUNT_ORDER = {acc_id: i for i, (acc_id, *_rest) in enumerate(CANONICAL_ACCOUNTS)}
STATEMENT_NAMES = {"PL": "Profit & Loss", "BS": "Balance Sheet", "CF": "Cash Flow"}

# Common-size bases: P&L lines are read as a share of revenue, balance sheet lines as a
# share of total assets (the two textbook vertical-analysis denominators).
_COMMON_SIZE_BASE = {"PL": "PL.REVENUE", "BS": "BS.TOTAL_ASSETS"}

# Profit bridge steps, in presentation order: (label, account_id, sign). sign=+1 means an
# increase in the account increases PAT (income), -1 means it reduces PAT (expense).
PROFIT_BRIDGE_STEPS: list[tuple[str, str, int]] = [
    ("Revenue", "PL.REVENUE", +1),
    ("Other income", "PL.OTHER_INCOME", +1),
    ("Cost of materials", "PL.COGS", -1),
    ("Purchases of stock-in-trade", "PL.PURCHASES_STOCK_IN_TRADE", -1),
    ("Changes in inventories", "PL.CHANGES_IN_INVENTORY", -1),
    ("Employee costs", "PL.EMPLOYEE_COST", -1),
    ("Other expenses", "PL.OTHER_EXPENSES", -1),
    ("Depreciation", "PL.DEPRECIATION", -1),
    ("Finance costs", "PL.FINANCE_COST", -1),
    ("Exceptional items", "PL.EXCEPTIONAL_ITEMS", -1),
    ("Tax", "PL.TAX", -1),
]

_CAGR_SERIES = [("Revenue", "PL.REVENUE", "revenue_cagr"), ("PAT", "PL.PAT", "pat_cagr"),
                ("Total assets", "BS.TOTAL_ASSETS", "total_assets_cagr")]



def _pct_change(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev in (None, 0):
        return None
    return (curr - prev) / abs(prev)


def cagr(first: float | None, last: float | None, years: float) -> float | None:
    """Compound annual growth. Undefined (None) for a non-positive start/end value or a
    span under a quarter of a year -- a CAGR across a sign change is meaningless."""
    if first is None or last is None or years < 0.25 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _years_between(d0: date, d1: date) -> float:
    """Whole months between period ends, in years. Period ends are month-ends, so FY-end to
    FY-end is exactly 1.0 -- a day count would make a leap-year span 1.002 years and turn a
    true 20% growth into 19.96%."""
    return ((d1.year - d0.year) * 12 + (d1.month - d0.month)) / 12


def statement_analysis(facts_by_period: dict[date, dict[str, float]]) -> dict[str, list[dict]]:
    """Horizontal + vertical analysis for every statement line present in the ledger."""
    periods = sorted(facts_by_period)
    out: dict[str, list[dict]] = {"PL": [], "BS": [], "CF": []}
    accounts = sorted({a for p in periods for a in facts_by_period[p]}, key=lambda a: ACCOUNT_ORDER.get(a, 999))
    for account_id in accounts:
        statement = account_id.split(".", 1)[0]
        if statement not in out:
            continue
        values = {p.isoformat(): facts_by_period[p].get(account_id) for p in periods}
        row: dict[str, Any] = {
            "account_id": account_id, "account_name": ACCOUNT_NAMES.get(account_id, account_id),
            "values": values, "change": {}, "change_pct": {}, "common_size": {},
        }
        for i, p in enumerate(periods):
            key = p.isoformat()
            curr = values[key]
            if i > 0:
                prev = values[periods[i - 1].isoformat()]
                row["change"][key] = (curr - prev) if curr is not None and prev is not None else None
                row["change_pct"][key] = _pct_change(curr, prev)
            base_account = _COMMON_SIZE_BASE.get(statement)
            if base_account:
                row["common_size"][key] = safe_div(curr, facts_by_period[p].get(base_account))
        out[statement].append(row)
    return out


def dupont(facts_by_period: dict[date, dict[str, float]]) -> list[dict]:
    rows = []
    for p in sorted(facts_by_period):
        f = facts_by_period[p]
        net_margin = safe_div(f.get("PL.PAT"), f.get("PL.REVENUE"))
        asset_turnover = safe_div(f.get("PL.REVENUE"), f.get("BS.TOTAL_ASSETS"))
        equity_mult = safe_div(f.get("BS.TOTAL_ASSETS"), f.get("BS.EQ.TOTAL"))
        if None in (net_margin, asset_turnover, equity_mult):
            continue
        rows.append({
            "period": p.isoformat(), "net_margin": net_margin, "asset_turnover": asset_turnover,
            "equity_multiplier": equity_mult, "roe": net_margin * asset_turnover * equity_mult,
        })
    return rows


def growth(facts_by_period: dict[date, dict[str, float]]) -> list[dict]:
    periods = sorted(facts_by_period)
    rows = []
    series_defs = list(_CAGR_SERIES)
    series_defs.insert(1, ("EBITDA", None, "ebitda_cagr"))
    for label, account_id, code in series_defs:
        points = []
        for p in periods:
            f = facts_by_period[p]
            try:
                v = _ebitda(f) if account_id is None else f.get(account_id)
            except KeyError:
                v = None
            if v is not None:
                points.append((p, v))
        if len(points) < 2:
            continue
        (p0, v0), (p1, v1) = points[0], points[-1]
        years = _years_between(p0, p1)
        rows.append({"label": label, "metric_code": code, "first_period": p0.isoformat(), "last_period": p1.isoformat(),
                     "first": v0, "last": v1, "years": round(years, 2), "cagr": cagr(v0, v1, years)})
    return rows


def _unclassified_expenses(f: dict[str, float]) -> float | None:
    """Stated total expenses not covered by any named expense line (captions the canonical
    chart has no line for). Exact, from the statement's own subtotal -- not a plug."""
    if "PL.TOTAL_EXPENSES" not in f:
        return None
    lines = sum(f.get(k, 0.0) for k in EXPENSE_LINES) - f.get("PL.EXPENSES_CAPITALISED", 0.0)
    return f["PL.TOTAL_EXPENSES"] - lines


def profit_bridge(facts_by_period: dict[date, dict[str, float]]) -> dict | None:
    """Walks PAT from the prior period to the latest one, each step the PAT impact of one
    line's change. Uses the same P&L structure as the reconciliation cascade: expense
    captions without a named line come from the stated total expenses, and exceptional
    items use their effect on profit (sign read from the statement, not assumed). A
    remaining difference is shown as 'Unreconciled difference' and flagged -- it can only
    appear when the P&L itself fails reconciliation, and the Data Diagnostic says where."""
    periods = sorted(p for p in facts_by_period if "PL.PAT" in facts_by_period[p])
    if len(periods) < 2:
        return None
    prev_p, curr_p = periods[-2], periods[-1]
    prev, curr = facts_by_period[prev_p], facts_by_period[curr_p]
    steps = [{"label": f"PAT {prev_p.isoformat()}", "amount": prev["PL.PAT"], "kind": "start"}]

    def add(label: str, impact: float, account_id: str | None) -> None:
        steps.append({"label": label, "amount": impact, "kind": "delta", "account_id": account_id})

    for label, account_id, sign in PROFIT_BRIDGE_STEPS:
        if account_id in ("PL.EXCEPTIONAL_ITEMS", "PL.TAX"):
            continue
        if account_id not in prev and account_id not in curr:
            continue
        add(label, sign * (curr.get(account_id, 0.0) - prev.get(account_id, 0.0)), account_id)
    if "PL.EXPENSES_CAPITALISED" in prev or "PL.EXPENSES_CAPITALISED" in curr:
        add("Expenditure capitalised",
            curr.get("PL.EXPENSES_CAPITALISED", 0.0) - prev.get("PL.EXPENSES_CAPITALISED", 0.0),
            "PL.EXPENSES_CAPITALISED")
    u_prev, u_curr = _unclassified_expenses(prev), _unclassified_expenses(curr)
    if u_prev is not None and u_curr is not None and (abs(u_prev) > 0.5 or abs(u_curr) > 0.5):
        add("Other expense captions", -(u_curr - u_prev), None)
    if "PL.EXCEPTIONAL_ITEMS" in prev or "PL.EXCEPTIONAL_ITEMS" in curr:
        add("Exceptional items", exceptional_effect(curr)[0] - exceptional_effect(prev)[0], "PL.EXCEPTIONAL_ITEMS")
    if "PL.TAX" in prev or "PL.TAX" in curr:
        add("Tax", -(curr.get("PL.TAX", 0.0) - prev.get("PL.TAX", 0.0)), "PL.TAX")

    explained = sum(s_["amount"] for s_ in steps if s_["kind"] == "delta")
    residual = (curr["PL.PAT"] - prev["PL.PAT"]) - explained
    tolerance = max(0.5, 0.005 * max(abs(prev["PL.PAT"]), abs(curr["PL.PAT"])))
    reconciled = abs(residual) <= tolerance
    if abs(residual) > 0.5:
        add("Unreconciled difference" if not reconciled else "Rounding", residual, None)
    steps.append({"label": f"PAT {curr_p.isoformat()}", "amount": curr["PL.PAT"], "kind": "end"})
    return {"from_period": prev_p.isoformat(), "to_period": curr_p.isoformat(), "steps": steps,
            "unexplained": residual, "reconciled": reconciled}


def leverage_liquidity(facts_by_period: dict[date, dict[str, float]]) -> list[dict]:
    rows = []
    for p in sorted(facts_by_period):
        f = facts_by_period[p]
        wc = (f["BS.CA.TOTAL"] - f["BS.CL.TOTAL"]) if "BS.CA.TOTAL" in f and "BS.CL.TOTAL" in f else None
        debt_parts = [f.get("BS.CL.SHORT_TERM_BORROWINGS"), f.get("BS.NCL.LONG_TERM_BORROWINGS")]
        total_debt = sum(v for v in debt_parts if v is not None) if any(v is not None for v in debt_parts) else None
        nd = total_debt - f["BS.CA.CASH"] if total_debt is not None and "BS.CA.CASH" in f else None
        try:
            ebitda_v = _ebitda(f)
        except KeyError:
            ebitda_v = None
        if wc is None and nd is None:
            continue
        rows.append({"period": p.isoformat(), "working_capital": wc, "total_debt": total_debt, "net_debt": nd,
                     "ebitda": ebitda_v, "net_debt_to_ebitda": safe_div(nd, ebitda_v)})
    return rows


def bank_analytics(transactions: list[dict]) -> dict:
    """transactions: [{txn_date: date|str, narration, debit, credit, balance}]."""
    if not transactions:
        return {"monthly": [], "top_inflows": [], "top_outflows": [], "totals": None}
    monthly: dict[str, dict] = defaultdict(lambda: {"inflow": 0.0, "outflow": 0.0, "txn_count": 0, "closing_balance": None})
    by_payer: dict[str, float] = defaultdict(float)
    by_payee: dict[str, float] = defaultdict(float)
    for t in sorted(transactions, key=lambda t: str(t.get("txn_date") or "")):
        month = str(t.get("txn_date") or "")[:7] or "unknown"
        m = monthly[month]
        credit, debit = float(t.get("credit") or 0), float(t.get("debit") or 0)
        m["inflow"] += credit
        m["outflow"] += debit
        m["txn_count"] += 1
        if t.get("balance") is not None:
            m["closing_balance"] = float(t["balance"])
        narration = (t.get("narration") or "Unlabelled").strip()
        if credit:
            by_payer[narration] += credit
        if debit:
            by_payee[narration] += debit
    monthly_rows = [{"month": k, **v, "net": v["inflow"] - v["outflow"]} for k, v in sorted(monthly.items())]
    total_in = sum(r["inflow"] for r in monthly_rows)
    total_out = sum(r["outflow"] for r in monthly_rows)

    def top(d: dict[str, float], total: float) -> list[dict]:
        return [{"counterparty": k, "amount": v, "share": safe_div(v, total)}
                for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:5]]

    return {
        "monthly": monthly_rows,
        "top_inflows": top(by_payer, total_in),
        "top_outflows": top(by_payee, total_out),
        "totals": {"inflow": total_in, "outflow": total_out, "net": total_in - total_out,
                   "months": len(monthly_rows), "txn_count": sum(r["txn_count"] for r in monthly_rows),
                   "avg_monthly_net": (total_in - total_out) / len(monthly_rows) if monthly_rows else None},
    }


def run_detailed_analysis(facts_by_period: dict[date, dict[str, float]], transactions: list[dict] | None = None) -> dict:
    """The full analysis bundle stored on the blackboard as `detailed_analysis`."""
    periods = sorted(facts_by_period)
    return {
        "periods": [p.isoformat() for p in periods],
        "statements": statement_analysis(facts_by_period),
        "dupont": dupont(facts_by_period),
        "growth": growth(facts_by_period),
        "profit_bridge": profit_bridge(facts_by_period),
        "leverage_liquidity": leverage_liquidity(facts_by_period),
        "bank": bank_analytics(transactions or []),
    }


def growth_metric_dicts(analysis: dict) -> list[dict]:
    """CAGR rows as metric-table entries (dated at the last period) so the report writer
    can cite them via {{m:revenue_cagr:<period>}} like any other metric."""
    out = []
    for g in analysis.get("growth", []):
        if g.get("cagr") is None:
            continue
        out.append({"metric_code": g["metric_code"], "period_end": date.fromisoformat(g["last_period"]),
                    "value": g["cagr"], "unit": "%", "formula_version": "1.0",
                    "inputs": [g["label"], g["first_period"], g["last_period"]]})
    return out


tool("analysis.detailed", allowed_agents=["detailed_analytics"])(run_detailed_analysis)
