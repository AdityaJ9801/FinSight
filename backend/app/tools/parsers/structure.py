"""Statement-structure awareness shared by the Excel and CSV parsers.

Real statements are not flat label/value lists:
- value-less heading rows ('Non-current liabilities', 'Financial liabilities',
  'Exceptional items:') give the rows beneath them their meaning -- 'Borrowings' under
  Non-current liabilities is long-term debt, under Current liabilities it's short-term debt;
- a sheet can hold several sub-tables whose columns are NOT periods (ageing buckets
  'Not Due | < 6 months', a debenture list 'Coupon | No. of debentures'); reading those
  cells as if they were the sheet's period columns manufactured facts out of ageing
  buckets and coupon rates.

SectionTracker keeps the heading path; `period_like` decides whether a sub-table header's
columns are reporting periods.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.coa import is_total_label, normalize_label

if TYPE_CHECKING:
    from app.tools.parsers import RawRow, RawTable

_PERIOD_HINT = re.compile(
    r"\b(?:19|20)\d{2}\b|\bFY\s*'?\d{2,4}\b|\b(?:Q[1-4]|H[12])\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)
_CURRENCY_SYMBOLS_RE = re.compile(r"[$€£₹¥]|rs\.?|inr|usd|eur|gbp|aed|sar|jpy|cny", re.IGNORECASE)

_DATE_COL_NAMES = {
    "date", "txn_date", "txn date", "transaction date", "value date", "posting date", "dt",
    "period", "month", "quarter", "time", "timestamp", "billing date", "invoice date", "trans_date"
}
_YEAR_COL_NAMES = {"year", "yr", "fiscal year", "fy", "financial year", "fiscal_year"}
_METRIC_KEYWORDS = {
    "sales", "revenue", "cogs", "cost", "profit", "income", "expense", "expenses",
    "gross", "margin", "ebitda", "ebit", "tax", "units", "price", "discount", "discounts",
    "debit", "credit", "balance", "amount", "qty", "quantity", "fee", "fees", "salary", "salaries",
    "turnover", "opex", "capex", "receipts", "billings"
}


def clean_numeric(val) -> float | None:
    """Universal robust numeric cleaner: handles currencies ($/₹/€/£), commas (including Indian
    lakhs/crores like 5,29,550.00), accounting negatives in parentheses ((1,234.50), $(500)),
    trailing minus, whitespace, tabs, and dashes/nil."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    s = s.replace("\t", " ").replace("\u00a0", " ").strip("\"' \t\r\n")
    if not s:
        return None

    is_neg = False
    if s.startswith("(") and s.endswith(")") and len(s) > 2:
        is_neg = True
        s = s[1:-1].strip()
    elif s.startswith("$(") and s.endswith(")") and len(s) > 3:
        is_neg = True
        s = s[2:-1].strip()
    elif s.endswith("-") and len(s) > 1 and s[:-1].strip().replace(",", "").replace(".", "").isdigit():
        is_neg = True
        s = s[:-1].strip()

    s = _CURRENCY_SYMBOLS_RE.sub("", s).strip()

    if s in ("-", "—", "–", "nil", "NIL", "Nil", "NA", "N/A", "null", "none", ""):
        return 0.0

    s = re.sub(r"(?<=[,\.])\s+", "", s)
    s = re.sub(r"[,.]{2,}", ".", s)
    if "." not in s and re.search(r",(\d{2})$", s):
        s = re.sub(r",(\d{2})$", r".\1", s)
    s = s.replace(",", "").strip()

    if s.startswith("-"):
        is_neg = True
        s = s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()

    try:
        val_float = float(s)
        return -val_float if is_neg else val_float
    except ValueError:
        return None


def detect_columnar_dataset(grid: list[list], header_idx: int = 0) -> bool:
    """Detects whether grid is a columnar/tabular dataset (metrics as columns, records as rows)
    rather than a wide financial statement (accounts as rows, time periods as columns)."""
    if len(grid) <= header_idx + 1:
        return False
    header = [str(c).strip() for c in grid[header_idx] if c is not None]
    if len(header) < 3:
        return False
    cols_norm = [c.lower() for c in header]
    metric_hits = sum(1 for c in cols_norm if any(k in c.split() or k in c for k in _METRIC_KEYWORDS))
    has_date_col = any(c in _DATE_COL_NAMES or any(k in c for k in _DATE_COL_NAMES) for c in cols_norm)
    has_year_col = any(c in _YEAR_COL_NAMES or any(k in c for k in _YEAR_COL_NAMES) for c in cols_norm)
    period_re = re.compile(r"\b(?:19|20)\d{2}\b|\bFY\s*'?\d{2,4}\b|\bQ[1-4]\b", re.IGNORECASE)
    period_col_count = sum(1 for c in header[1:] if period_re.search(c))

    if period_col_count >= max(2, len(header[1:]) * 0.5):
        return False
    if metric_hits >= 2 and (has_date_col or has_year_col or len(grid) > 5):
        return True
    return False


is_columnar_dataset = detect_columnar_dataset


def parse_columnar_dataset(grid: list[list], header_idx: int = 0, name: str = "data") -> list:
    """Parses a columnar table into:
    1. A financial_summary RawTable (aggregates metrics across periods e.g. annual)
    2. A records RawTable (detailed raw rows with clean numbers)
    Also attaches structured_dataset (dimensions, measures, typed records, aggregations)
    for dynamic attribute analytics, attribute-based charting and chat querying."""
    from app.tools.parsers import RawRow, RawTable

    raw_header = [str(c).strip() if c is not None else "" for c in grid[header_idx]]
    start_data_idx = header_idx + 1

    # Check for two-tier multi-row headers (e.g. ERP headers: 'Debit', 'Credit' followed by 'Amount', 'Amount')
    if header_idx + 1 < len(grid):
        next_row = grid[header_idx + 1]
        next_vals = [str(c).strip() if c is not None else "" for c in next_row]
        has_subheaders = any(next_vals) and not any(clean_numeric(c) is not None for c in next_vals if c)
        if has_subheaders:
            merged_header = []
            for j in range(max(len(raw_header), len(next_vals))):
                h1 = raw_header[j] if j < len(raw_header) else ""
                h2 = next_vals[j] if j < len(next_vals) else ""
                if h1 and h2 and h1.lower() != h2.lower():
                    merged_header.append(f"{h1} {h2}".strip())
                elif h1:
                    merged_header.append(h1)
                elif h2:
                    merged_header.append(h2)
                else:
                    merged_header.append("")
            raw_header = merged_header
            start_data_idx = header_idx + 2

    # Clean header strings and de-duplicate
    header = []
    seen_cols: dict[str, int] = {}
    for c in raw_header:
        base = c.strip() or "Col"
        if base in seen_cols:
            seen_cols[base] += 1
            header.append(f"{base}_{seen_cols[base]}")
        else:
            seen_cols[base] = 0
            header.append(base)

    date_col_idx = next((i for i, c in enumerate(header) if c.lower() in _DATE_COL_NAMES or any(k in c.lower() for k in _DATE_COL_NAMES)), None)
    year_col_idx = next((i for i, c in enumerate(header) if c.lower() in _YEAR_COL_NAMES or any(k in c.lower() for k in _YEAR_COL_NAMES)), None)

    numeric_cols: dict[str, int] = {}
    for idx, col in enumerate(header):
        if idx in (date_col_idx, year_col_idx):
            continue
        nums = [clean_numeric(r[idx]) for r in grid[start_data_idx:] if idx < len(r)]
        valid_nums = sum(1 for n in nums if n is not None)
        if valid_nums >= max(1, (len(grid) - start_data_idx) * 0.25):
            numeric_cols[col] = idx

    row_periods: list[str | None] = []
    distinct_periods: set[str] = set()

    for row in grid[start_data_idx:]:
        p = None
        if year_col_idx is not None and year_col_idx < len(row):
            y_str = str(row[year_col_idx]).strip()
            if y_str.isdigit() and len(y_str) == 4:
                p = f"{y_str}-12-31"
        if not p and date_col_idx is not None and date_col_idx < len(row):
            d_str = str(row[date_col_idx]).strip()
            for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y",
                        "%b-%y", "%b-%Y", "%B %Y", "%d %b %Y", "%Y/%m/%d", "%m-%d-%Y"):
                try:
                    dt = datetime.strptime(d_str, fmt).date()
                    p = dt.isoformat()
                    break
                except ValueError:
                    pass
            if not p:
                m_y = re.search(r"\b(20\d{2}|19\d{2})\b", d_str)
                if m_y:
                    p = f"{m_y.group(1)}-12-31"
        row_periods.append(p)
        if p:
            distinct_periods.add(p)

    sorted_periods = sorted(distinct_periods)
    if not sorted_periods:
        sorted_periods = ["current_period"]

    metric_cols_clean = {k: v for k, v in numeric_cols.items() if k.lower() not in ("month number", "id", "row", "index")}
    if not metric_cols_clean:
        metric_cols_clean = numeric_cols

    summary_data = {col: {p: 0.0 for p in sorted_periods} for col in metric_cols_clean}

    for r_idx, row in enumerate(grid[start_data_idx:]):
        p = row_periods[r_idx] or sorted_periods[0]
        first_metric = list(metric_cols_clean.keys())[0] if metric_cols_clean else None
        if first_metric and p not in summary_data[first_metric]:
            m_y = re.search(r"\b(20\d{2}|19\d{2})\b", str(p))
            if m_y:
                p_match = next((sp for sp in sorted_periods if m_y.group(1) in sp), None)
                p = p_match or sorted_periods[0]
            else:
                p = sorted_periods[0]

        for col, c_idx in metric_cols_clean.items():
            if c_idx < len(row):
                val = clean_numeric(row[c_idx])
                if val is not None:
                    summary_data[col][p] += val

    summary_rows: list[RawRow] = []
    for r_i, (metric_name, vals) in enumerate(summary_data.items(), start=1):
        summary_rows.append(RawRow(
            row_idx=r_i,
            label=metric_name,
            values=vals,
            source_ref={"source": f"{name}_summary", "metric": metric_name},
        ))

    summary_table = RawTable(rows=summary_rows, periods=sorted_periods, name=f"{name}_summary")

    record_rows: list[RawRow] = []
    for r_i, row in enumerate(grid[start_data_idx:], start=start_data_idx + 1):
        row_vals: dict[str, float] = {}
        for col_name, c_idx in numeric_cols.items():
            if c_idx < len(row):
                v = clean_numeric(row[c_idx])
                if v is not None:
                    row_vals[col_name] = v
        label_parts = [str(row[c]).strip() for c in range(min(3, len(row))) if c not in numeric_cols.values() and row[c] not in (None, "")]
        lbl = " - ".join(label_parts) if label_parts else f"Record_{r_i}"
        if row_vals:
            record_rows.append(RawRow(
                row_idx=r_i,
                label=lbl,
                values=row_vals,
                source_ref={"row": r_i},
            ))

    records_table = RawTable(rows=record_rows, periods=list(numeric_cols.keys()), name=f"{name}_records")

    # Dimensions & Structured Dataset Extraction
    dim_cols = [c for c in header if c not in numeric_cols and c.lower() not in ("id", "index") and c.strip()]
    records: list[dict] = []
    for row in grid[start_data_idx:]:
        if not any(c not in (None, "") for c in row):
            continue
        rec: dict = {}
        for c_idx, col in enumerate(header):
            if not col or c_idx >= len(row):
                continue
            val = row[c_idx]
            if col in numeric_cols:
                n_val = clean_numeric(val)
                rec[col] = n_val if n_val is not None else 0.0
            else:
                rec[col] = str(val).strip() if val is not None else ""
        if rec:
            records.append(rec)

    # Precompute aggregations for dimensions with reasonable cardinality (2 to 60)
    aggregations: dict[str, dict] = {}
    for dim in dim_cols:
        val_counts: dict[str, int] = {}
        for r in records:
            v = str(r.get(dim, "")).strip()
            if v:
                val_counts[v] = val_counts.get(v, 0) + 1
        if 2 <= len(val_counts) <= 60:
            agg_dim: dict[str, dict] = {}
            for r in records:
                v = str(r.get(dim, "")).strip()
                if not v:
                    continue
                if v not in agg_dim:
                    agg_dim[v] = {m: 0.0 for m in metric_cols_clean}
                    agg_dim[v]["_count"] = 0
                for m in metric_cols_clean:
                    agg_dim[v][m] += float(r.get(m, 0.0) or 0.0)
                agg_dim[v]["_count"] += 1
            for v, m_dict in agg_dim.items():
                for m in metric_cols_clean:
                    m_dict[m] = round(m_dict[m], 2)
            aggregations[dim] = agg_dim

    structured_dataset = {
        "name": name,
        "dimensions": dim_cols,
        "measures": list(metric_cols_clean.keys()),
        "records": records[:3000],
        "row_count": len(records),
        "aggregations": aggregations,
    }
    summary_table.dataset = structured_dataset
    records_table.dataset = structured_dataset

    return [summary_table, records_table]


# Headings that open a top-level section of a statement (anything else is a sub-heading
# nested under the current top-level section).
_MAJOR = re.compile(
    r"^(?:non[- ]current (?:assets|liabilities)|current (?:assets|liabilities)|equity|assets|liabilities|"
    r"equity and liabilities|income|revenue|expenses|expenditure|exceptional items?|tax expenses?|"
    r"income tax expenses?|other comprehensive income|earnings per (?:equity )?share|"
    r"\(?[a-d]\)? ?cash flows? (?:from|used in)|cash flows? from)",
)


def period_like(text) -> bool:
    return bool(text) and bool(_PERIOD_HINT.search(str(text)))


def leading_indent(raw_label: str) -> int:
    return len(raw_label) - len(raw_label.lstrip(" \t"))


class SectionTracker:
    def __init__(self):
        self.root: str | None = None   # ALL-CAPS banner, e.g. 'EQUITY AND LIABILITIES'
        self.major: str | None = None  # e.g. 'Current liabilities'
        self.minor: str | None = None  # e.g. 'Financial liabilities'
        self.minor_indent = 0
        self._children_indented = False

    def heading(self, raw_label: str, indent: int) -> None:
        label = raw_label.strip().rstrip(":").strip()
        if not label:
            return
        norm = normalize_label(label)
        letters = [c for c in label if c.isalpha()]
        if letters and all(c.isupper() for c in letters) and len(letters) > 3:
            self.root, self.major, self.minor = label, None, None
        elif _MAJOR.match(norm):
            self.major, self.minor = label, None
        else:
            self.minor, self.minor_indent, self._children_indented = label, indent, False

    def data_row(self, raw_label: str, indent: int) -> str:
        """Section path for a data row; also closes sub-groups and sections as they end."""
        if self.minor is not None:
            if indent > self.minor_indent:
                self._children_indented = True
            elif self._children_indented:
                # back at the sub-heading's own indentation after indented children: the
                # sub-group ended ('Provisions' after '  Borrowings', '  Lease liabilities'
                # under 'Financial liabilities')
                self.minor, self._children_indented = None, False
        path = " > ".join(p for p in (self.root, self.major, self.minor) if p)
        if is_total_label(raw_label):  # 'Total current liabilities' closes 'Current liabilities'
            n = normalize_label(raw_label)
            if self.major and normalize_label(self.major) in n:
                self.major, self.minor = None, None
            elif self.minor and normalize_label(self.minor) in n:
                self.minor = None
        return path
