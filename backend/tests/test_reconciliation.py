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


def test_pl_subtotals_multi_step_cogs_reconciliation():
    # 2019 data from multi-step Profit and loss statement:
    # Total Income: 15,00,000, COGS: 4,25,850, Stated Total Expenses (Operating): 1,38,875,
    # Net Other Income: -12,500, Stated PAT: 9,22,775
    f_2019 = {
        "PL.REVENUE": 1500000.0,
        "PL.TOTAL_INCOME": 1500000.0,
        "PL.COGS": 425850.0,
        "PL.TOTAL_EXPENSES": 138875.0,
        "PL.OTHER_INCOME": -12500.0,
        "PL.TAX": 570.0,
        "PL.PAT": 922775.0,
    }
    result = check_pl_subtotals(f_2019)
    assert result is not None
    assert result["status"] == "pass", f"Expected pass, got: {result}"
    assert result["expected"] == 922775.0

    # 2021 data: Total Income: 24,37,500, COGS: 20,87,867.30, Operating Expenses: 1,09,625,
    # Net Other Income: -40,000, Stated PAT: 2,00,007.70
    f_2021 = {
        "PL.REVENUE": 2437500.0,
        "PL.TOTAL_INCOME": 2437500.0,
        "PL.COGS": 2087867.30,
        "PL.TOTAL_EXPENSES": 109625.0,
        "PL.OTHER_INCOME": -40000.0,
        "PL.TAX": 12000.0,
        "PL.PAT": 200007.70,
    }
    result_2021 = check_pl_subtotals(f_2021)
    assert result_2021["status"] == "pass", f"Expected pass, got: {result_2021}"

    # 2022 data: Total Income: 36,56,250, COGS: 27,66,207.75, Operating Expenses: 3,51,770,
    # Net Other Income: -50,000, Stated PAT: 4,88,272.25
    f_2022 = {
        "PL.REVENUE": 3656250.0,
        "PL.TOTAL_INCOME": 3656250.0,
        "PL.COGS": 2766207.75,
        "PL.TOTAL_EXPENSES": 351770.0,
        "PL.OTHER_INCOME": -50000.0,
        "PL.TAX": 22000.0,
        "PL.PAT": 488272.25,
    }
    result_2022 = check_pl_subtotals(f_2022)
    assert result_2022["status"] == "pass", f"Expected pass, got: {result_2022}"


