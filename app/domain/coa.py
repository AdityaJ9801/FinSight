"""Canonical chart of accounts (Schedule III-aligned subset) and the label-synonym table
used by both the rule-based mapper pass and the schema-mapper's LLM fallback (design doc
§2 principle 3: "deterministic first, LLM as fallback").
"""
from __future__ import annotations

import re

# (id, name, statement, parent_id, normal_balance)
CANONICAL_ACCOUNTS: list[tuple[str, str, str, str | None, str]] = [
    # --- Balance sheet: assets ---
    ("BS.CA.CASH", "Cash and Cash Equivalents", "BS", None, "debit"),
    ("BS.CA.TRADE_RECEIVABLES", "Trade Receivables", "BS", None, "debit"),
    ("BS.CA.INVENTORY", "Inventories", "BS", None, "debit"),
    ("BS.CA.OTHER", "Other Current Assets", "BS", None, "debit"),
    ("BS.CA.TOTAL", "Total Current Assets", "BS", None, "debit"),
    ("BS.NCA.PPE", "Property, Plant and Equipment", "BS", None, "debit"),
    ("BS.NCA.OTHER", "Other Non-Current Assets", "BS", None, "debit"),
    ("BS.NCA.TOTAL", "Total Non-Current Assets", "BS", None, "debit"),
    ("BS.TOTAL_ASSETS", "Total Assets", "BS", None, "debit"),
    # --- Balance sheet: liabilities ---
    ("BS.CL.TRADE_PAYABLES", "Trade Payables", "BS", None, "credit"),
    ("BS.CL.SHORT_TERM_BORROWINGS", "Short-term Borrowings", "BS", None, "credit"),
    ("BS.CL.OTHER", "Other Current Liabilities", "BS", None, "credit"),
    ("BS.CL.TOTAL", "Total Current Liabilities", "BS", None, "credit"),
    ("BS.NCL.LONG_TERM_BORROWINGS", "Long-term Borrowings", "BS", None, "credit"),
    ("BS.NCL.OTHER", "Other Non-Current Liabilities", "BS", None, "credit"),
    ("BS.NCL.TOTAL", "Total Non-Current Liabilities", "BS", None, "credit"),
    # --- Balance sheet: equity ---
    ("BS.EQ.SHARE_CAPITAL", "Share Capital", "BS", None, "credit"),
    ("BS.EQ.RESERVES", "Reserves and Surplus", "BS", None, "credit"),
    ("BS.EQ.TOTAL", "Total Equity", "BS", None, "credit"),
    ("BS.TOTAL_EQUITY_LIAB", "Total Equity and Liabilities", "BS", None, "credit"),
    # --- P&L ---
    ("PL.REVENUE", "Revenue from Operations", "PL", None, "credit"),
    ("PL.OTHER_INCOME", "Other Income", "PL", None, "credit"),
    ("PL.TOTAL_INCOME", "Total Income", "PL", None, "credit"),
    ("PL.COGS", "Cost of Materials Consumed", "PL", None, "debit"),
    ("PL.EMPLOYEE_COST", "Employee Benefit Expense", "PL", None, "debit"),
    ("PL.OTHER_EXPENSES", "Other Expenses", "PL", None, "debit"),
    ("PL.DEPRECIATION", "Depreciation and Amortization Expense", "PL", None, "debit"),
    ("PL.FINANCE_COST", "Finance Costs", "PL", None, "debit"),
    ("PL.EBITDA", "EBITDA", "PL", None, "credit"),
    ("PL.PBT", "Profit Before Tax", "PL", None, "credit"),
    ("PL.TAX", "Tax Expense", "PL", None, "debit"),
    ("PL.PAT", "Profit After Tax", "PL", None, "credit"),
    # Per-share ratios, not aggregatable amounts -- kept separate from PL.PAT so they can
    # never be summed/overwritten into it (see LABEL_SYNONYMS: "basic"/"diluted" alone,
    # without "earnings per share" in the label, is genuinely ambiguous to an LLM and was
    # confirmed live to get mis-mapped into PL.PAT, corrupting the PL_SUBTOTALS reconciliation
    # check with a ~9000x-too-small "PAT").
    ("PL.EPS_BASIC", "Basic Earnings Per Share", "PL", None, "credit"),
    ("PL.EPS_DILUTED", "Diluted Earnings Per Share", "PL", None, "credit"),
    # Standard Schedule III P&L captions with no natural home in the accounts above --
    # without their own accounts they were getting force-fit (at low confidence) into
    # PL.COGS/PL.OTHER_EXPENSES, which PL_SUBTOTALS's recompute formula then either
    # dropped (once same-account facts stopped being blindly summed) or double-counted.
    # Optional in the formula (default 0) since not every statement reports them.
    ("PL.PURCHASES_STOCK_IN_TRADE", "Purchases of Stock-in-Trade", "PL", None, "debit"),
    ("PL.CHANGES_IN_INVENTORY", "Changes in Inventories", "PL", None, "debit"),
    ("PL.EXCEPTIONAL_ITEMS", "Exceptional Items", "PL", None, "debit"),
    # --- Cash flow ---
    ("CF.OPERATING", "Net Cash from Operating Activities", "CF", None, "debit"),
    ("CF.INVESTING", "Net Cash from Investing Activities", "CF", None, "debit"),
    ("CF.FINANCING", "Net Cash from Financing Activities", "CF", None, "debit"),
    ("CF.NET_CHANGE", "Net Change in Cash", "CF", None, "debit"),
    ("CF.OPENING_CASH", "Opening Cash Balance", "CF", None, "debit"),
    ("CF.CLOSING_CASH", "Closing Cash Balance", "CF", None, "debit"),
]

# normalized source label -> canonical account id. Extend freely; this is the "memory
# seed" for layouts you haven't seen yet. Real per-tenant learned mappings live in the
# account_mappings table and are checked before this table.
LABEL_SYNONYMS: dict[str, str] = {
    "cash and cash equivalents": "BS.CA.CASH",
    "cash & cash equivalents": "BS.CA.CASH",
    "cash in hand": "BS.CA.CASH",
    "cash and bank balances": "BS.CA.CASH",
    "trade receivables": "BS.CA.TRADE_RECEIVABLES",
    "sundry debtors": "BS.CA.TRADE_RECEIVABLES",
    "accounts receivable": "BS.CA.TRADE_RECEIVABLES",
    "inventories": "BS.CA.INVENTORY",
    "stock in trade": "BS.CA.INVENTORY",
    "inventory": "BS.CA.INVENTORY",
    "other current assets": "BS.CA.OTHER",
    "total current assets": "BS.CA.TOTAL",
    "property plant and equipment": "BS.NCA.PPE",
    "property, plant and equipment": "BS.NCA.PPE",
    "fixed assets": "BS.NCA.PPE",
    "net block": "BS.NCA.PPE",
    "other non current assets": "BS.NCA.OTHER",
    "other non-current assets": "BS.NCA.OTHER",
    "total non current assets": "BS.NCA.TOTAL",
    "total non-current assets": "BS.NCA.TOTAL",
    "total assets": "BS.TOTAL_ASSETS",
    "trade payables": "BS.CL.TRADE_PAYABLES",
    "sundry creditors": "BS.CL.TRADE_PAYABLES",
    "accounts payable": "BS.CL.TRADE_PAYABLES",
    "short term borrowings": "BS.CL.SHORT_TERM_BORROWINGS",
    "short-term borrowings": "BS.CL.SHORT_TERM_BORROWINGS",
    "other current liabilities": "BS.CL.OTHER",
    "total current liabilities": "BS.CL.TOTAL",
    "long term borrowings": "BS.NCL.LONG_TERM_BORROWINGS",
    "long-term borrowings": "BS.NCL.LONG_TERM_BORROWINGS",
    "term loans": "BS.NCL.LONG_TERM_BORROWINGS",
    "other non current liabilities": "BS.NCL.OTHER",
    "other non-current liabilities": "BS.NCL.OTHER",
    "total non current liabilities": "BS.NCL.TOTAL",
    "total non-current liabilities": "BS.NCL.TOTAL",
    "share capital": "BS.EQ.SHARE_CAPITAL",
    "equity share capital": "BS.EQ.SHARE_CAPITAL",
    "reserves and surplus": "BS.EQ.RESERVES",
    "reserves & surplus": "BS.EQ.RESERVES",
    "total equity": "BS.EQ.TOTAL",
    "total shareholders funds": "BS.EQ.TOTAL",
    "total shareholders' funds": "BS.EQ.TOTAL",
    "total equity and liabilities": "BS.TOTAL_EQUITY_LIAB",
    "total liabilities and equity": "BS.TOTAL_EQUITY_LIAB",
    "revenue from operations": "PL.REVENUE",
    "net sales": "PL.REVENUE",
    "sales": "PL.REVENUE",
    "turnover": "PL.REVENUE",
    "other income": "PL.OTHER_INCOME",
    "total income": "PL.TOTAL_INCOME",
    "total revenue": "PL.TOTAL_INCOME",
    "cost of materials consumed": "PL.COGS",
    "cost of goods sold": "PL.COGS",
    "purchases": "PL.COGS",
    "employee benefit expense": "PL.EMPLOYEE_COST",
    "employee benefits expense": "PL.EMPLOYEE_COST",
    "salaries and wages": "PL.EMPLOYEE_COST",
    "other expenses": "PL.OTHER_EXPENSES",
    "depreciation and amortization expense": "PL.DEPRECIATION",
    "depreciation and amortisation expense": "PL.DEPRECIATION",
    "depreciation": "PL.DEPRECIATION",
    "finance costs": "PL.FINANCE_COST",
    "interest expense": "PL.FINANCE_COST",
    "ebitda": "PL.EBITDA",
    "profit before tax": "PL.PBT",
    "pbt": "PL.PBT",
    "tax expense": "PL.TAX",
    "provision for tax": "PL.TAX",
    "profit after tax": "PL.PAT",
    "net profit": "PL.PAT",
    "profit for the year": "PL.PAT",
    "pat": "PL.PAT",
    # Schedule III P&L statements always end with an "Earnings per equity share" block
    # whose two rows are commonly just "Basic"/"Diluted" with the EPS context carried by a
    # section header above them, not the row label itself -- a real, standard layout, not a
    # hypothetical, so these are deterministic synonyms rather than left for the LLM to guess.
    "basic": "PL.EPS_BASIC",
    "diluted": "PL.EPS_DILUTED",
    "basic eps": "PL.EPS_BASIC",
    "diluted eps": "PL.EPS_DILUTED",
    "basic earnings per share": "PL.EPS_BASIC",
    "diluted earnings per share": "PL.EPS_DILUTED",
    "basic in rs": "PL.EPS_BASIC",
    "diluted in rs": "PL.EPS_DILUTED",
    "earnings per share basic": "PL.EPS_BASIC",
    "earnings per share diluted": "PL.EPS_DILUTED",
    "purchases of stock-in-trade": "PL.PURCHASES_STOCK_IN_TRADE",
    "purchases of stock in trade": "PL.PURCHASES_STOCK_IN_TRADE",
    "changes in inventories": "PL.CHANGES_IN_INVENTORY",
    "changes in inventory": "PL.CHANGES_IN_INVENTORY",
    "exceptional items": "PL.EXCEPTIONAL_ITEMS",
    # normalize_label strips punctuation entirely (not to a space), so "Exceptional
    # (income)/expenses" normalizes to this concatenated form -- verified against
    # normalize_label directly, not guessed.
    "exceptional incomeexpenses": "PL.EXCEPTIONAL_ITEMS",
    "net cash from operating activities": "CF.OPERATING",
    "net cash generated from operating activities": "CF.OPERATING",
    "net cash used in operating activities": "CF.OPERATING",
    "net cash from investing activities": "CF.INVESTING",
    "net cash used in investing activities": "CF.INVESTING",
    "net cash from financing activities": "CF.FINANCING",
    "net cash used in financing activities": "CF.FINANCING",
    "net increase in cash and cash equivalents": "CF.NET_CHANGE",
    "net change in cash": "CF.NET_CHANGE",
    "cash and cash equivalents at beginning of year": "CF.OPENING_CASH",
    "opening cash balance": "CF.OPENING_CASH",
    "cash and cash equivalents at end of year": "CF.CLOSING_CASH",
    "closing cash balance": "CF.CLOSING_CASH",
}


ACCOUNT_STATEMENT: dict[str, str] = {acc_id: statement for acc_id, _, statement, _, _ in CANONICAL_ACCOUNTS}

# The only accounts genuinely meant to catch several distinct, unrelated line items in one
# period (mapper.py's own low-confidence/out-of-allowlist fallback target is BS.CA.OTHER) --
# every other account, including ones literally named "Other Income"/"Other Expenses", is a
# specific Schedule III statement line that should appear at most once per period. Confirmed
# live: without this distinction, low-confidence LLM mappings of a P&L sheet's "Other
# Comprehensive Income"/tax-reconciliation disclosure rows into PL.OTHER_INCOME/PL.TAX
# alongside the real line item summed together into a wildly wrong figure and broke the
# PL_SUBTOTALS reconciliation check.
DUMPING_GROUND_ACCOUNTS: frozenset[str] = frozenset({
    "BS.CA.OTHER", "BS.NCA.OTHER", "BS.CL.OTHER", "BS.NCL.OTHER",
})


def normalize_label(label: str) -> str:
    label = label.strip().lower()
    label = re.sub(r"[^a-z0-9&' \-]", "", label)
    label = re.sub(r"\s+", " ", label)
    return label.strip()


def infer_statement_hint(table_name: str | None) -> str | None:
    """Only fires for sheets/tables unambiguously identifiable as one of the three primary
    statements -- supplementary schedules (ageing, inventory, loan notes, tax filings) stay
    unrestricted since they legitimately reference concepts from more than one statement
    (e.g. a tax note citing "Profit before tax"). Confirmed live: a real Cash Flow Statement
    sheet's non-cash add-back rows ("Depreciation and amortisation expense", "Finance
    costs", ...) reuse the EXACT label text of the corresponding P&L expense rows, so
    without this, both resolve to the same PL.* account for the same period and get summed
    together -- doubling the real expense and badly corrupting the PL_SUBTOTALS reconciliation
    check (and every ratio/insight computed from PL.* metrics)."""
    if not table_name:
        return None
    name = table_name.strip().lower()
    if "cash flow" in name:
        return "CF"
    if "balance sheet" in name:
        return "BS"
    if "profit and loss" in name or "profit & loss" in name or "p&l" in name or "p & l" in name or "income statement" in name:
        return "PL"
    return None


def lookup_synonym(label: str, statement_hint: str | None = None) -> str | None:
    account_id = LABEL_SYNONYMS.get(normalize_label(label))
    if account_id is None:
        return None
    if statement_hint is not None and ACCOUNT_STATEMENT.get(account_id) != statement_hint:
        # Same label text, wrong statement for this sheet (e.g. a CF add-back row that
        # happens to repeat a PL expense's name) -- reject the rule match so it falls
        # through to the LLM fallback (also statement-scoped) instead of silently
        # colliding with the real fact from the sheet it actually belongs to.
        return None
    return account_id
