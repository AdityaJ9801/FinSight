"""Reconciliation checks (design doc §6.5). Deterministic; the reconciler agent only adds a
plain-language explanation on top when a check fails. Each check returns None if it can't
run (required accounts not present) rather than a false pass/fail.
"""
from __future__ import annotations

from datetime import date

TOLERANCE_PCT = 0.001  # 0.1%
TOLERANCE_ABS = 1.0    # ₹1 (in the document's own unit scale)


def _within_tolerance(expected: float, actual: float) -> bool:
    diff = abs(expected - actual)
    return diff <= TOLERANCE_ABS or diff <= abs(expected) * TOLERANCE_PCT


def check_bs_balance(f: dict) -> dict | None:
    if "BS.TOTAL_ASSETS" not in f or "BS.TOTAL_EQUITY_LIAB" not in f:
        return None
    expected, actual = f["BS.TOTAL_ASSETS"], f["BS.TOTAL_EQUITY_LIAB"]
    ok = _within_tolerance(expected, actual)
    return {
        "check_code": "BS_BALANCE", "status": "pass" if ok else "fail",
        "expected": expected, "actual": actual, "diff": actual - expected,
        "details": {"rule": "Total Assets = Total Equity and Liabilities"},
    }


def check_pl_subtotals(f: dict) -> dict | None:
    required = ["PL.REVENUE", "PL.OTHER_INCOME", "PL.COGS", "PL.EMPLOYEE_COST",
                "PL.OTHER_EXPENSES", "PL.DEPRECIATION", "PL.FINANCE_COST", "PL.TAX", "PL.PAT"]
    if not all(k in f for k in required):
        return None
    # These three Schedule III captions aren't reported by every company (a subset CoA
    # can't have a named account for every possible caption), so they're optional --
    # included only when actually present, rather than skipping the whole check.
    optional_expense = (
        f.get("PL.PURCHASES_STOCK_IN_TRADE", 0) + f.get("PL.CHANGES_IN_INVENTORY", 0)
        + f.get("PL.EXCEPTIONAL_ITEMS", 0)
    )
    recomputed_pbt = (
        f["PL.REVENUE"] + f["PL.OTHER_INCOME"] - f["PL.COGS"] - f["PL.EMPLOYEE_COST"]
        - f["PL.OTHER_EXPENSES"] - f["PL.DEPRECIATION"] - f["PL.FINANCE_COST"] - optional_expense
    )
    recomputed_pat = recomputed_pbt - f["PL.TAX"]
    ok = _within_tolerance(recomputed_pat, f["PL.PAT"])
    return {
        "check_code": "PL_SUBTOTALS", "status": "pass" if ok else "fail",
        "expected": recomputed_pat, "actual": f["PL.PAT"], "diff": f["PL.PAT"] - recomputed_pat,
        "details": {"rule": "Recomputed PAT = stated PAT"},
    }


def check_pl_bs_link(f: dict, f_prev: dict | None) -> dict | None:
    if f_prev is None or "BS.EQ.RESERVES" not in f or "BS.EQ.RESERVES" not in f_prev or "PL.PAT" not in f:
        return None
    expected_closing = f_prev["BS.EQ.RESERVES"] + f["PL.PAT"]
    actual_closing = f["BS.EQ.RESERVES"]
    diff_pct = abs(expected_closing - actual_closing) / abs(expected_closing) if expected_closing else 0
    ok = diff_pct <= 0.01
    return {
        "check_code": "PL_BS_LINK", "status": "pass" if ok else "fail",
        "expected": expected_closing, "actual": actual_closing, "diff": actual_closing - expected_closing,
        "details": {"rule": "Opening reserves + PAT (no dividend data) ~= closing reserves", "tolerance": "1%"},
    }


def check_cf_cash_tie(f: dict) -> dict | None:
    required = ["CF.OPENING_CASH", "CF.NET_CHANGE", "CF.CLOSING_CASH", "BS.CA.CASH"]
    if not all(k in f for k in required):
        return None
    expected_closing = f["CF.OPENING_CASH"] + f["CF.NET_CHANGE"]
    ok_internal = _within_tolerance(expected_closing, f["CF.CLOSING_CASH"])
    ok_bs = _within_tolerance(f["CF.CLOSING_CASH"], f["BS.CA.CASH"])
    ok = ok_internal and ok_bs
    return {
        "check_code": "CF_CASH_TIE", "status": "pass" if ok else "fail",
        "expected": expected_closing, "actual": f["CF.CLOSING_CASH"], "diff": f["CF.CLOSING_CASH"] - expected_closing,
        "details": {"rule": "Opening cash + net change = closing cash = BS cash", "bs_cash_match": ok_bs},
    }


def check_bank_running(transactions: list[dict]) -> dict | None:
    if not transactions:
        return None
    sorted_txns = sorted(transactions, key=lambda t: (t.get("txn_date") or "", t.get("row_idx", 0)))
    mismatches = []
    prev_balance = None
    for t in sorted_txns:
        if t.get("balance") is None:
            prev_balance = None
            continue
        if prev_balance is not None:
            expected = prev_balance + (t.get("credit") or 0) - (t.get("debit") or 0)
            if not _within_tolerance(expected, t["balance"]):
                mismatches.append({"row_idx": t.get("row_idx"), "expected": expected, "actual": t["balance"]})
        prev_balance = t["balance"]

    return {
        "check_code": "BANK_RUNNING", "status": "pass" if not mismatches else "fail",
        "expected": None, "actual": None, "diff": len(mismatches),
        "details": {"mismatches": mismatches[:20]},
    }


def check_duplicates(shas: list[str]) -> dict:
    seen = set()
    dupes = [s for s in shas if s in seen or seen.add(s)]
    return {
        "check_code": "DUPLICATES", "status": "pass" if not dupes else "fail",
        "expected": None, "actual": None, "diff": len(dupes),
        "details": {"duplicate_hashes": list(set(dupes))},
    }


def within_materiality(payload: dict, materiality_pct: float) -> bool:
    """True if a failed reconciliation check's gap is small enough (relative to the
    expected value) to log as a gap instead of blocking. NO_FACTS has no "expected" value
    to be relative to (an empty dataset isn't a materiality question), so it always blocks.
    Pure function of the review item's own payload + the configured threshold, so it can be
    re-evaluated later (e.g. by the report writer, to describe what was auto-approved)
    without needing a separate persisted flag on the item."""
    if payload.get("check_code") == "NO_FACTS":
        return False
    expected, diff = payload.get("expected"), payload.get("diff")
    if expected in (None, 0) or diff is None:
        return False
    return abs(diff) / abs(expected) <= materiality_pct


def run_statement_checks(facts_by_period: dict[date, dict[str, float]]) -> list[dict]:
    """Runs the statement-level checks (BS/PL/CF) across every period present."""
    results = []
    periods_sorted = sorted(facts_by_period.keys())
    for i, period in enumerate(periods_sorted):
        f = facts_by_period[period]
        f_prev = facts_by_period[periods_sorted[i - 1]] if i > 0 else None
        for check_fn, needs_prev in ((check_bs_balance, False), (check_pl_subtotals, False), (check_cf_cash_tie, False)):
            result = check_fn(f)
            if result:
                result["period_end"] = period
                results.append(result)
        link = check_pl_bs_link(f, f_prev)
        if link:
            link["period_end"] = period
            results.append(link)
    return results
