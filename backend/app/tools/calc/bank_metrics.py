"""Bank-statement analytics: deterministic cash metrics computed straight from
BankTransaction rows, for analyses (e.g. the bank_statement_review template) where there is
no balance sheet or P&L to feed the statement-based REGISTRY in metrics.py.

Monthly series are keyed to each calendar month's last day; statement-level summaries are
keyed to the last month end in the statement, so every value binds to a {{m:code:period}}
placeholder exactly like a statement metric. Like the rest of the calc layer, the LLM only
interprets these numbers -- it never produces them.
"""
from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import date

from app.tools.registry import tool

BANK_METRIC_UNITS: dict[str, str] = {
    "bank_inflows": "INR",
    "bank_outflows": "INR",
    "bank_net_flow": "INR",
    "bank_closing_balance": "INR",
    "bank_avg_monthly_inflow": "INR",
    "bank_avg_monthly_outflow": "INR",
    "bank_min_balance": "INR",
    "bank_cash_cover_months": "months",
    "bank_top_payer_share": "%",
    "bank_negative_month_share": "%",
}

# Narration boilerplate that says how money moved, not who it came from.
_NOISE = re.compile(
    r"\b(neft|rtgs|imps|upi|ach|nach|ecs|chq|cheque|cr|dr|trf|transfer|by|to|from|payment|received|"
    r"receipt|customer|inward|outward|ref|txn|no)\b|[^a-z ]", re.I,
)


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def payer_key(narration: str | None, counterparty: str | None) -> str | None:
    """Best-effort payer identity for concentration: the explicit counterparty if the parser
    found one, else the narration stripped of payment-rail boilerplate and reference numbers."""
    if counterparty and counterparty.strip():
        return counterparty.strip().lower()
    if not narration:
        return None
    key = " ".join(_NOISE.sub(" ", narration.lower()).split())
    return key or None


def compute_bank_metrics(transactions: list[dict]) -> list[dict]:
    """transactions: [{txn_date: date, debit, credit, balance|None, narration, counterparty}].
    Returns metric dicts in the same shape as metrics.compute_all, ready for persist_metrics."""
    txns = sorted((t for t in transactions if t.get("txn_date")), key=lambda t: t["txn_date"])
    if not txns:
        return []

    monthly: dict[date, dict] = defaultdict(lambda: {"in": 0.0, "out": 0.0, "closing": None})
    payers: dict[str, float] = defaultdict(float)
    balances: list[float] = []
    for t in txns:
        bucket = monthly[_month_end(t["txn_date"])]
        credit, debit = float(t.get("credit") or 0), float(t.get("debit") or 0)
        bucket["in"] += credit
        bucket["out"] += debit
        if t.get("balance") is not None:
            bucket["closing"] = float(t["balance"])  # rows are date-sorted, so the last one wins
            balances.append(float(t["balance"]))
        if credit > 0:
            key = payer_key(t.get("narration"), t.get("counterparty"))
            if key:
                payers[key] += credit

    def row(code: str, period: date, value: float | None, inputs: list[str]) -> dict | None:
        if value is None:
            return None
        return {"metric_code": code, "period_end": period, "value": value, "unit": BANK_METRIC_UNITS[code],
                "formula_version": "1.0", "inputs": inputs, "group": "bank"}

    out: list[dict | None] = []
    for period, b in sorted(monthly.items()):
        out.append(row("bank_inflows", period, b["in"], ["bank.credit"]))
        out.append(row("bank_outflows", period, b["out"], ["bank.debit"]))
        out.append(row("bank_net_flow", period, b["in"] - b["out"], ["bank.credit", "bank.debit"]))
        out.append(row("bank_closing_balance", period, b["closing"], ["bank.balance"]))

    last = max(monthly)
    months = len(monthly)
    total_in = sum(b["in"] for b in monthly.values())
    total_out = sum(b["out"] for b in monthly.values())
    avg_out = total_out / months
    closing = monthly[last]["closing"]

    out.append(row("bank_avg_monthly_inflow", last, total_in / months, ["bank.credit"]))
    out.append(row("bank_avg_monthly_outflow", last, avg_out, ["bank.debit"]))
    out.append(row("bank_min_balance", last, min(balances) if balances else None, ["bank.balance"]))
    out.append(row("bank_cash_cover_months", last, closing / avg_out if closing is not None and avg_out > 0 else None,
                   ["bank.balance", "bank.debit"]))
    out.append(row("bank_top_payer_share", last, max(payers.values()) / total_in if payers and total_in > 0 else None,
                   ["bank.credit"]))
    out.append(row("bank_negative_month_share", last,
                   sum(1 for b in monthly.values() if b["in"] - b["out"] < 0) / months, ["bank.credit", "bank.debit"]))
    return [r for r in out if r is not None]


def transactions_as_dicts(rows) -> list[dict]:
    """BankTransaction ORM rows -> the plain dicts compute_bank_metrics expects."""
    return [{"txn_date": t.txn_date, "debit": t.debit, "credit": t.credit, "balance": t.balance,
             "narration": t.narration, "counterparty": t.counterparty} for t in rows]


tool("bank.compute_metrics", allowed_agents=["cash_wc", "risk", "insight_reasoner"])(compute_bank_metrics)
