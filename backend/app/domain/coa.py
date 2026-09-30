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
    # Ind AS / Schedule III subtotals and captions that real statements always carry. Without
    # named accounts they were force-fit into PL.OTHER_EXPENSES / PL.PBT / PL.OTHER_INCOME by
    # low-confidence guesses and broke the P&L tie-out (confirmed on a real listed-company
    # workbook: "Total expenses", "Profit before exceptional items and tax", OCI lines).
    ("PL.TOTAL_EXPENSES", "Total Expenses", "PL", None, "debit"),
    ("PL.EXPENSES_CAPITALISED", "Expenditure Transferred to Capital Account", "PL", None, "credit"),
    ("PL.PBEIT", "Profit Before Exceptional Items and Tax", "PL", None, "credit"),
    ("PL.OCI", "Other Comprehensive Income", "PL", None, "credit"),
    ("PL.TOTAL_COMPREHENSIVE_INCOME", "Total Comprehensive Income", "PL", None, "credit"),
    ("BS.TOTAL_LIABILITIES", "Total Liabilities", "BS", None, "credit"),
    # --- Cash flow ---
    ("CF.OPERATING", "Net Cash from Operating Activities", "CF", None, "debit"),
    ("CF.INVESTING", "Net Cash from Investing Activities", "CF", None, "debit"),
    ("CF.FINANCING", "Net Cash from Financing Activities", "CF", None, "debit"),
    ("CF.NET_CHANGE", "Net Change in Cash", "CF", None, "debit"),
    ("CF.OPENING_CASH", "Opening Cash Balance", "CF", None, "debit"),
    ("CF.CLOSING_CASH", "Closing Cash Balance", "CF", None, "debit"),
    ("CF.DIVIDENDS_PAID", "Dividends Paid", "CF", None, "credit"),
    # Capital expenditure (cash paid for PPE / intangibles), from the investing section --
    # needed for a standard free cash flow (OCF - capex) instead of OCF + all investing
    # cash flows, which counted acquisitions of subsidiaries and financial investments as
    # if they were capex.
    ("CF.CAPEX", "Capital Expenditure (Purchase of PPE and Intangibles)", "CF", None, "credit"),
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
    # --- Ind AS captions (listed-company layouts) ---
    "other equity": "BS.EQ.RESERVES",
    "total liabilities": "BS.TOTAL_LIABILITIES",
    "total expenses": "PL.TOTAL_EXPENSES",
    "total expenditure": "PL.TOTAL_EXPENSES",
    "expenditure transferred to capital account": "PL.EXPENSES_CAPITALISED",
    "expenditure transferred to capital and other accounts": "PL.EXPENSES_CAPITALISED",
    "expenses capitalised": "PL.EXPENSES_CAPITALISED",
    "profit before exceptional items and tax": "PL.PBEIT",
    "profit before exceptional items and taxes": "PL.PBEIT",
    "profitloss before exceptional items and tax": "PL.PBEIT",
    "total exceptional items": "PL.EXCEPTIONAL_ITEMS",
    "exceptional items net": "PL.EXCEPTIONAL_ITEMS",
    "total tax expense": "PL.TAX",
    "total tax expenses": "PL.TAX",
    "total income tax expense": "PL.TAX",
    "profitloss for the year": "PL.PAT",
    "profit for the period": "PL.PAT",
    "total other comprehensive income for the year": "PL.OCI",
    "total other comprehensive income": "PL.OCI",
    "other comprehensive income for the year": "PL.OCI",
    "total comprehensive income for the year": "PL.TOTAL_COMPREHENSIVE_INCOME",
    "total comprehensive income": "PL.TOTAL_COMPREHENSIVE_INCOME",
    "changes in inventories of finished goods work-in-progress and stock-in-trade": "PL.CHANGES_IN_INVENTORY",
    "changes in inventories of finishedsemi-finished goods stock-in-trade & wip": "PL.CHANGES_IN_INVENTORY",
    "cost of raw materials consumed": "PL.COGS",
    "net cash fromused in operating activities": "CF.OPERATING",
    "net cash generated fromused in operating activities": "CF.OPERATING",
    "net cash fromused in investing activities": "CF.INVESTING",
    "net cash fromused in financing activities": "CF.FINANCING",
    "net increasedecrease in cash and cash equivalents": "CF.NET_CHANGE",
    "opening cash and cash equivalents": "CF.OPENING_CASH",
    "closing cash and cash equivalents": "CF.CLOSING_CASH",
    "cash and cash equivalents at the beginning of the year": "CF.OPENING_CASH",
    "cash and cash equivalents at the end of the year": "CF.CLOSING_CASH",
    # Note/schedule totals of statement lines -- used to tie schedules back to the statements
    "total inventories": "BS.CA.INVENTORY",
    "total trade receivables": "BS.CA.TRADE_RECEIVABLES",
    "total trade receivables net": "BS.CA.TRADE_RECEIVABLES",
    "total trade payables": "BS.CL.TRADE_PAYABLES",
    "purchase of capital assets": "CF.CAPEX",
    "purchase of property plant and equipment": "CF.CAPEX",
    "purchase of property plant and equipment and intangible assets": "CF.CAPEX",
    "purchases of property plant and equipment": "CF.CAPEX",
    "acquisition of property plant and equipment": "CF.CAPEX",
    "payments for property plant and equipment": "CF.CAPEX",
    "purchase of fixed assets": "CF.CAPEX",
    "purchase of tangible and intangible assets": "CF.CAPEX",
    "purchase of intangible assets": "CF.CAPEX",
    "capital expenditure": "CF.CAPEX",
    "capital expenditure on fixed assets": "CF.CAPEX",
    "dividend paid": "CF.DIVIDENDS_PAID",
    "dividends paid": "CF.DIVIDENDS_PAID",
    "dividends paid to equity shareholders": "CF.DIVIDENDS_PAID",
}

# Special account id a mapper may return for a row that has no place in the canonical
# ledger (a disclosure, ratio, count, sub-schedule breakdown, loan-by-loan list...). Such
# rows produce no fact at all -- they used to be forced into BS.CA.OTHER at low confidence,
# which summed hundreds of unrelated note rows into "other current assets".
UNMAPPED = "UNMAPPED"

# Labels whose meaning depends on the statement section they appear under ("Borrowings"
# under Non-current liabilities vs Current liabilities). Resolved by contextual_account().
_SECTION_SIDES = [
    # (substring in the normalized section path, side) -- checked most-specific first
    ("non-current assets", "NCA"), ("non current assets", "NCA"), ("fixed assets", "NCA"),
    ("current assets", "CA"),
    ("non-current liabilities", "NCL"), ("non current liabilities", "NCL"),
    ("current liabilities", "CL"),
    ("equity", "EQ"),
]
_SIDE_OTHER = {"NCA": "BS.NCA.OTHER", "CA": "BS.CA.OTHER", "NCL": "BS.NCL.OTHER", "CL": "BS.CL.OTHER"}
_BORROWING_LABELS = {"borrowings", "loans and borrowings", "borrowing", "debt", "loans from banks"}

# P&L sections whose rows are components of one canonical account; the section's own
# "Total ..." row wins over its components when present (see facts.py resolution).
_PL_SECTION_ACCOUNTS = [
    ("other comprehensive income", "PL.OCI"),
    ("exceptional item", "PL.EXCEPTIONAL_ITEMS"),
    ("tax expense", "PL.TAX"),
    ("income tax", "PL.TAX"),
]

_LEADING_NOISE = re.compile(r"^(?:\(?[a-z]{1,4}\)|\(?[ivxlc]{1,5}\)|[a-z]\.|\d+[.)]|less:?|add:?)\s+", re.IGNORECASE)


def section_side(section: str | None) -> str | None:
    if not section:
        return None
    s = normalize_label(section)
    for needle, side in _SECTION_SIDES:
        if needle in s:
            return side
    return None


def strip_label_noise(label: str) -> str:
    """'(a) Raw materials' -> 'Raw materials'; 'Less: Expenditure ...' -> 'Expenditure ...'."""
    out = label.strip()
    for _ in range(3):
        new = _LEADING_NOISE.sub("", out).strip()
        if new == out:
            break
        out = new
    return out


def is_total_label(label: str) -> bool:
    n = normalize_label(label)
    return n.startswith(("total", "subtotal", "sub-total", "sub total", "grand total"))


def contextual_account(label: str, section: str | None, statement: str | None) -> str | None:
    """Section-aware mapping for labels whose account depends on where they sit. Only
    returns an answer when the context makes it unambiguous."""
    n = normalize_label(strip_label_noise(label))
    if statement in (None, "BS"):
        side = section_side(section)
        if n in _BORROWING_LABELS or n.startswith("borrowings"):
            if side == "NCL":
                return "BS.NCL.LONG_TERM_BORROWINGS"
            if side == "CL":
                return "BS.CL.SHORT_TERM_BORROWINGS"
    if statement in (None, "PL") and section:
        s = normalize_label(section)
        for needle, account in _PL_SECTION_ACCOUNTS:
            if needle in s and not n.startswith("earnings per"):
                return account
    return None


def section_other_bucket(section: str | None) -> str | None:
    """The balance-sheet side bucket for an otherwise-unmatched line inside a primary balance
    sheet (e.g. 'Right-of-use assets' under Non-current assets -> BS.NCA.OTHER)."""
    return _SIDE_OTHER.get(section_side(section))


_UNIT_PATTERNS = [
    (re.compile(r"\b(?:in\s+)?(?:rs\.?|inr|₹)?\s*crores?\b|\bcr\.?\)|\(₹\s*cr\b", re.IGNORECASE), 10_000_000),
    (re.compile(r"\blakhs?\b|\blacs?\b", re.IGNORECASE), 100_000),
    (re.compile(r"\bbillions?\b|\bbn\b", re.IGNORECASE), 1_000_000_000),
    (re.compile(r"\bmillions?\b|\bmn\b", re.IGNORECASE), 1_000_000),
    (re.compile(r"'000|\bthousands?\b|\bin\s+000s?\b|\(000\)", re.IGNORECASE), 1_000),
]


def detect_unit_scale(text: str) -> float | None:
    """Deterministic unit-scale detection from a document's header/metadata text ('(₹
    crore)', 'Rs. in lakhs', "INR '000"). The LLM classifier's guess varied by model (one
    returned 1 for a '(₹ crore)' workbook, another 10^7), so a stated unit always wins."""
    for pattern, scale in _UNIT_PATTERNS:
        if pattern.search(text or ""):
            return float(scale)
    return None


# Sheets that are notes/schedules supporting the primary statements. Their rows break a
# statement line down (loan-by-loan lists, ageing buckets, inventory categories) or disclose
# non-ledger facts, so they must never be added into the primary statement accounts.
_SUPPORTING_SHEET_WORDS = ("ageing", "aging", "schedule", "note", "inventor", "loan", "borrowing", "tax",
                           "receivable", "payable", "debtor", "creditor", "register", "gst", "fixed asset",
                           "ppe", "segment", "related part", "contingent", "lease", "employee", "share capital")


def sheet_role(table_name: str | None, doc_type: str | None, rule_hits: set[str]) -> str:
    """'primary' for a sheet/table that IS a financial statement, 'supporting' otherwise.
    Decided by sheet name first, then by whether its rows contain a statement's defining
    totals (a sheet that states Total Assets / PAT / Net cash from operations is a statement)."""
    if infer_statement_hint(table_name):
        return "primary"
    name = (table_name or "").strip().lower()
    if name and any(w in name for w in _SUPPORTING_SHEET_WORDS):
        return "supporting"
    anchors = {"BS.TOTAL_ASSETS", "BS.TOTAL_EQUITY_LIAB", "PL.PAT", "PL.PBT", "PL.REVENUE", "CF.OPERATING",
               "CF.NET_CHANGE"}
    if rule_hits & anchors and len(rule_hits) >= 3:
        return "primary"
    if doc_type in ("balance_sheet", "pnl", "cash_flow", "trial_balance") and not name:
        return "primary"  # a single-table CSV/PDF classified as a statement
    return "supporting"


def lookup_prefix_synonym(label: str, statement_hint: str | None = None) -> str | None:
    """'Trade payables — dues of micro & small enterprises' -> BS.CL.TRADE_PAYABLES: the
    longest multi-word synonym that the label starts with. Single-word keys ('sales',
    'purchases', 'basic') are excluded -- too easy to match the wrong line."""
    n = normalize_label(strip_label_noise(label))
    best = None
    for key, account_id in LABEL_SYNONYMS.items():
        if " " not in key or not n.startswith(key + " "):
            continue
        if statement_hint is not None and ACCOUNT_STATEMENT.get(account_id) != statement_hint:
            continue
        if best is None or len(key) > len(best[0]):
            best = (key, account_id)
    return best[1] if best else None


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
    account_id = LABEL_SYNONYMS.get(normalize_label(label)) or LABEL_SYNONYMS.get(normalize_label(strip_label_noise(label)))
    if account_id is None:
        return None
    if statement_hint is not None and ACCOUNT_STATEMENT.get(account_id) != statement_hint:
        # Same label text, wrong statement for this sheet (e.g. a CF add-back row that
        # happens to repeat a PL expense's name) -- reject the rule match so it falls
        # through to the LLM fallback (also statement-scoped) instead of silently
        # colliding with the real fact from the sheet it actually belongs to.
        return None
    return account_id
