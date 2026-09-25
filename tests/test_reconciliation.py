from datetime import date

from app.domain.validation_rules import check_bank_running, check_bs_balance, check_pl_subtotals


def test_bs_balance_passes_when_tied():
    f = {"BS.TOTAL_ASSETS": 11500000, "BS.TOTAL_EQUITY_LIAB": 11500000}
    result = check_bs_balance(f)
    assert result["status"] == "pass"


def test_bs_balance_fails_when_not_tied():
    f = {"BS.TOTAL_ASSETS": 11500000, "BS.TOTAL_EQUITY_LIAB": 11000000}
    result = check_bs_balance(f)
    assert result["status"] == "fail"
    assert result["diff"] == -500000


def test_pl_subtotals_recomputation():
    f = {
        "PL.REVENUE": 12000000, "PL.OTHER_INCOME": 120000, "PL.COGS": 7000000,
        "PL.EMPLOYEE_COST": 1800000, "PL.OTHER_EXPENSES": 900000, "PL.DEPRECIATION": 350000,
        "PL.FINANCE_COST": 250000, "PL.TAX": 455000, "PL.PAT": 1365000,
    }
    result = check_pl_subtotals(f)
    assert result["status"] == "pass"


def test_bank_running_balance_catches_mismatch():
    transactions = [
        {"row_idx": 1, "txn_date": "2024-01-01", "debit": 0, "credit": 0, "balance": 100},
        {"row_idx": 2, "txn_date": "2024-01-02", "debit": 0, "credit": 50, "balance": 999},  # wrong
    ]
    result = check_bank_running(transactions)
    assert result["status"] == "fail"
    assert result["details"]["mismatches"][0]["row_idx"] == 2
