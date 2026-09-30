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


EXPENSE_LINES = ("PL.COGS", "PL.PURCHASES_STOCK_IN_TRADE", "PL.CHANGES_IN_INVENTORY", "PL.EMPLOYEE_COST",
                 "PL.FINANCE_COST", "PL.DEPRECIATION", "PL.OTHER_EXPENSES")


def exceptional_effect(f: dict) -> tuple[float, str]:
    """Signed effect of exceptional items on profit, and how the sign was decided.

    Statements present exceptional items either as an expense (positive = loss) or as
    'income/(expense)' (negative = loss). Taking the stored value as an expense blindly
    doubled a loss into a gain on a real statement. The stated subtotals decide: PBT - PBEIT
    is the effect when both are reported; otherwise the sign that ties to the stated PBT."""
    x = f.get("PL.EXCEPTIONAL_ITEMS")
    if x is None:
        return 0.0, "none"
    if "PL.PBT" in f and "PL.PBEIT" in f:
        effect = f["PL.PBT"] - f["PL.PBEIT"]
        return effect, "from stated subtotals"
    base = pl_pbeit(f)[0]
    if base is not None and "PL.PBT" in f:
        as_expense, as_income = base - x, base + x
        if abs(as_income - f["PL.PBT"]) < abs(as_expense - f["PL.PBT"]):
            return x, "sign inferred from stated PBT"
        return -x, "sign inferred from stated PBT"
    return (-x if x > 0 else x), "assumed a loss"


def pl_expenses(f: dict) -> tuple[float | None, str]:
    """Total expenses: the stated total when reported, else the sum of expense lines net of
    expenditure transferred to capital."""
    if "PL.TOTAL_EXPENSES" in f:
        return f["PL.TOTAL_EXPENSES"], "stated"
    if not any(k in f for k in EXPENSE_LINES):
        return None, "missing"
    return sum(f.get(k, 0.0) for k in EXPENSE_LINES) - f.get("PL.EXPENSES_CAPITALISED", 0.0), "sum of lines"


def pl_income(f: dict) -> float | None:
    if "PL.TOTAL_INCOME" in f:
        return f["PL.TOTAL_INCOME"]
    if "PL.REVENUE" not in f:
        return None
    return f["PL.REVENUE"] + f.get("PL.OTHER_INCOME", 0.0)


def pl_pbeit(f: dict) -> tuple[float | None, str]:
    """Profit before exceptional items and tax: stated, else income - expenses."""
    if "PL.PBEIT" in f:
        return f["PL.PBEIT"], "stated"
    income, (expenses, _how) = pl_income(f), pl_expenses(f)
    if income is None or expenses is None:
        return None, "missing"
    return income - expenses, "recomputed"


def _result(code: str, expected: float, actual: float, rule: str, **details) -> dict:
    ok = _within_tolerance(expected, actual)
    return {"check_code": code, "status": "pass" if ok else "fail", "expected": expected, "actual": actual,
            "diff": actual - expected, "details": {"rule": rule, **details}}


def check_pl_cascade(f: dict) -> list[dict]:
    """The P&L proven step by step, so a gap is located instead of reported as one lump:

      PL_EXPENSE_LINES  sum of expense lines - capitalised = stated total expenses
      PL_OPERATING      total income - total expenses      = profit before exceptional & tax
      PL_EXCEPTIONAL    PBEIT + exceptional effect         = profit before tax
      PL_TAX            PBT - tax                          = profit after tax
      PL_SUBTOTALS      PAT recomputed through the most reliable path = stated PAT

    Each step runs only when its inputs exist; a statement with no P&L produces nothing,
    one with a P&L but missing inputs produces a 'skipped' entry saying which.
    """
    if "PL.PAT" not in f and "PL.REVENUE" not in f:
        return []
    out: list[dict] = []
    if "PL.TOTAL_EXPENSES" in f and any(k in f for k in EXPENSE_LINES):
        lines = sum(f.get(k, 0.0) for k in EXPENSE_LINES) - f.get("PL.EXPENSES_CAPITALISED", 0.0)
        r = _result("PL_EXPENSE_LINES", lines, f["PL.TOTAL_EXPENSES"],
                    "Expense lines - expenditure capitalised = total expenses",
                    hint="a gap is an expense caption with no canonical line; profit still ties to the stated total")
        if r["status"] == "fail":
            # Classification gap, not an arithmetic one: every profit figure uses the stated
            # total expenses, and the bridge shows the gap as 'Other expense captions'.
            r["status"] = "warn"
        out.append(r)
    income, (expenses, how) = pl_income(f), pl_expenses(f)
    if "PL.PBEIT" in f and income is not None and expenses is not None:
        out.append(_result("PL_OPERATING", income - expenses, f["PL.PBEIT"],
                           "Total income - total expenses = profit before exceptional items and tax",
                           expenses_basis=how))
    if "PL.PBT" in f and "PL.PBEIT" in f:
        effect, _ = exceptional_effect(f)
        out.append(_result("PL_EXCEPTIONAL", f["PL.PBEIT"] + effect, f["PL.PBT"],
                           "Profit before exceptional items + exceptional items = PBT"))
    if "PL.PBT" in f and "PL.TAX" in f and "PL.PAT" in f:
        out.append(_result("PL_TAX", f["PL.PBT"] - f["PL.TAX"], f["PL.PAT"], "PBT - tax = PAT"))

    pbeit, pbeit_how = pl_pbeit(f)
    missing = [k for k, ok in (("profit before exceptional items / expenses", pbeit is not None),
                               ("tax", "PL.TAX" in f), ("profit after tax", "PL.PAT" in f)) if not ok]
    if missing:
        out.append({"check_code": "PL_SUBTOTALS", "status": "skipped", "expected": None, "actual": None, "diff": None,
                    "details": {"rule": "Recomputed PAT = stated PAT",
                                "reason": "cannot recompute: missing " + ", ".join(missing)}})
    else:
        effect, effect_how = exceptional_effect(f)
        recomputed = pbeit + effect - f["PL.TAX"]
        out.append(_result("PL_SUBTOTALS", recomputed, f["PL.PAT"], "Recomputed PAT = stated PAT",
                           pbeit_basis=pbeit_how, exceptional_sign=effect_how))
    return out


def check_bs_sides(f: dict) -> list[dict]:
    """Each side of the balance sheet foots: current + non-current = total assets, and
    equity + liabilities = total equity and liabilities (when those subtotals are stated)."""
    out = []
    if all(k in f for k in ("BS.CA.TOTAL", "BS.NCA.TOTAL", "BS.TOTAL_ASSETS")):
        out.append(_result("BS_ASSET_SIDE", f["BS.CA.TOTAL"] + f["BS.NCA.TOTAL"], f["BS.TOTAL_ASSETS"],
                           "Current + non-current assets = total assets"))
    if all(k in f for k in ("BS.CL.TOTAL", "BS.NCL.TOTAL", "BS.EQ.TOTAL", "BS.TOTAL_EQUITY_LIAB")):
        out.append(_result("BS_FUNDING_SIDE", f["BS.EQ.TOTAL"] + f["BS.NCL.TOTAL"] + f["BS.CL.TOTAL"],
                           f["BS.TOTAL_EQUITY_LIAB"], "Equity + non-current + current liabilities = total"))
    return out


def check_pl_subtotals(f: dict) -> dict | None:
    """Backward-compatible single-result view of the cascade's overall PAT check."""
    for r in check_pl_cascade(f):
        if r["check_code"] == "PL_SUBTOTALS" and r["status"] != "skipped":
            return r
    return None


def check_pl_bs_link(f: dict, f_prev: dict | None) -> dict | None:
    """Opening reserves + total comprehensive income - dividends = closing reserves.

    Using PAT alone ignored other comprehensive income and dividends, so a statement that
    ties exactly failed this check by ~5% and blocked the job. Uses total comprehensive
    income when reported (else PAT + OCI, else PAT) and dividends paid from the cash flow
    statement. Without dividend data the movement can't be fully explained: a shortfall
    (consistent with distributions, buybacks, transfers) is then a warning, not a failure."""
    if f_prev is None or "BS.EQ.RESERVES" not in f or "BS.EQ.RESERVES" not in f_prev or "PL.PAT" not in f:
        return None
    if "PL.TOTAL_COMPREHENSIVE_INCOME" in f:
        income, basis = f["PL.TOTAL_COMPREHENSIVE_INCOME"], "total comprehensive income"
    elif "PL.OCI" in f:
        income, basis = f["PL.PAT"] + f["PL.OCI"], "PAT + OCI"
    else:
        income, basis = f["PL.PAT"], "PAT (no OCI reported)"
    dividends = abs(f["CF.DIVIDENDS_PAID"]) if "CF.DIVIDENDS_PAID" in f else None
    expected_closing = f_prev["BS.EQ.RESERVES"] + income - (dividends or 0.0)
    actual_closing = f["BS.EQ.RESERVES"]
    diff = actual_closing - expected_closing
    ok = abs(diff) <= max(TOLERANCE_ABS, abs(expected_closing) * 0.01)
    if ok:
        status = "pass"
    elif dividends is None and diff < 0:
        status = "warn"
    else:
        status = "fail"
    return {
        "check_code": "PL_BS_LINK", "status": status,
        "expected": expected_closing, "actual": actual_closing, "diff": diff,
        "details": {"rule": f"Opening reserves + {basis} - dividends paid = closing reserves",
                    "dividends": "from cash flow statement" if dividends is not None else "not reported",
                    "tolerance": "1%"},
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
        period_results = [r for r in (check_bs_balance(f), check_cf_cash_tie(f)) if r]
        period_results += check_bs_sides(f) + check_pl_cascade(f)
        for result in period_results:
            result["period_end"] = period
            results.append(result)
        link = check_pl_bs_link(f, f_prev)
        if link:
            link["period_end"] = period
            results.append(link)
    return results
