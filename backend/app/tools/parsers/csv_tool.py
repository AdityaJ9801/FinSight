from __future__ import annotations

import csv as _csv
import io
import re

from app.tools.parsers import RawRow, RawTable
from app.tools.parsers.structure import (
    SectionTracker,
    clean_numeric,
    detect_columnar_dataset,
    is_columnar_dataset,
    leading_indent,
    parse_columnar_dataset,
    period_like,
)
from app.tools.registry import tool
from app.tools.table_detect import detect_header_row_heuristic


_CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]


def _guess_delimiter(sample: str) -> str:
    """Counting delimiter occurrences across the sample is robust against preambles."""
    counts = {d: sample.count(d) for d in _CANDIDATE_DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _read_grid(file_path: str) -> list[list[str]]:
    raw_bytes = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(file_path, "r", newline="", encoding=enc) as f:
                content = f.read()
                raw_bytes = content
                break
        except (UnicodeDecodeError, LookupError):
            continue
    if raw_bytes is None:
        with open(file_path, "r", newline="", encoding="utf-8", errors="replace") as f:
            raw_bytes = f.read()

    # Clean null bytes if any
    raw_bytes = raw_bytes.replace("\x00", "")
    sample = raw_bytes[:8192]
    delimiter = _guess_delimiter(sample)
    reader = _csv.reader(io.StringIO(raw_bytes), delimiter=delimiter)
    return list(reader)


def read_csv_grid(file_path: str, max_rows: int = 30) -> list[list[str]]:
    """Raw rows, no header assumed -- used for header-row detection (heuristic or LLM)."""
    return _read_grid(file_path)[:max_rows]


def build_table_from_grid(grid: list[list[str]], header_row_idx: int, name: str = "csv") -> RawTable:
    """Builds a RawTable for standard matrix financial statements (line items as rows,
    period dates as columns). For columnar datasets, delegates to parse_columnar_dataset."""
    if is_columnar_dataset(grid, header_row_idx):
        tables = parse_columnar_dataset(grid, header_row_idx, name=name)
        return tables[0] if tables else RawTable(rows=[], periods=[], name=name)

    return _build_matrix_table(grid, header_row_idx, name=name)


def _build_matrix_table(grid: list[list[str]], header_row_idx: int, name: str = "csv") -> RawTable:
    if header_row_idx < 0 or header_row_idx >= len(grid):
        header_row_idx = 0
    header = [c.strip() if c else "" for c in grid[header_row_idx]]

    # Detect label column index: find first column with non-numeric text labels
    label_col_idx = 0
    if len(header) > 2 and len(grid) > header_row_idx + 1:
        # If column 0 is empty, row number, or S.No in data rows while column 1 has text
        c0_vals = [grid[r][0].strip() for r in range(header_row_idx + 1, min(header_row_idx + 8, len(grid))) if len(grid[r]) > 0]
        c1_vals = [grid[r][1].strip() for r in range(header_row_idx + 1, min(header_row_idx + 8, len(grid))) if len(grid[r]) > 1]
        if all(v.isdigit() or not v or len(v) <= 3 for v in c0_vals) and any(clean_numeric(v) is None and len(v) > 3 for v in c1_vals):
            label_col_idx = 1

    active_cols = [(j, c.strip()) for j, c in enumerate(header) if j > label_col_idx and c.strip()]
    periods = [c for _, c in active_cols]

    sections = SectionTracker()
    raw_rows: list[RawRow] = []

    for i, row in enumerate(grid[header_row_idx + 1:], start=header_row_idx + 2):
        if not row:
            continue
        # Extract label from label_col_idx or find first text column
        if label_col_idx < len(row) and row[label_col_idx].strip():
            raw_label, label = row[label_col_idx], row[label_col_idx].strip()
        else:
            non_empty = [(idx, c) for idx, c in enumerate(row) if c.strip()]
            first_text = next(((idx, c) for idx, c in non_empty if clean_numeric(c) is None), None)
            if not first_text:
                continue
            raw_label, label = row[first_text[0]], first_text[1].strip()

        indent = leading_indent(raw_label)
        others = [c for j, c in enumerate(row) if j != label_col_idx and c.strip()]
        if not others:
            sections.heading(raw_label, indent)
            continue

        if all(clean_numeric(c) is None for c in others):
            text_cells = [c.strip() for c in others if c.strip()]
            is_subtable = len(text_cells) >= 2 and all(re.search(r"[a-zA-Z]", c) for c in text_cells)
            if is_subtable:
                new_period_cols = [(j, c.strip()) for j, c in enumerate(row) if j > label_col_idx and period_like(c)]
                if new_period_cols:
                    active_cols = new_period_cols
                else:
                    active_cols = []
            sections.heading(label, indent)
            continue

        values: dict[str, float] = {}
        for j, period in active_cols:
            if j >= len(row):
                continue
            v = clean_numeric(row[j])
            if v is not None:
                values[period] = v

        if not values:
            continue

        section = sections.data_row(raw_label, indent)
        raw_rows.append(RawRow(
            row_idx=i, label=label, values=values, indent_level=indent, section=section,
            source_ref={"row": i, "label": label, "section": section}
        ))

    return RawTable(rows=raw_rows, periods=periods, name=name)


def read_csv_tables(file_path: str, header_row_idx: int | None = None) -> list[RawTable]:
    """Reads all tables out of a CSV. For columnar datasets, returns [summary_table, records_table].
    For wide statements, returns [statement_table]."""
    grid = _read_grid(file_path)
    if len(grid) < 2:
        return [RawTable(rows=[], periods=[], name="csv")]

    if header_row_idx is None:
        header_row_idx = detect_header_row_heuristic(grid)
        if header_row_idx is None:
            header_row_idx = 0

    if is_columnar_dataset(grid, header_row_idx):
        return parse_columnar_dataset(grid, header_row_idx, name="csv")

    table = _build_matrix_table(grid, header_row_idx, name="csv")
    return [table] if table else []


def read_csv(file_path: str, header_row_idx: int | None = None) -> RawTable:
    """Legacy interface: returns the primary/summary table."""
    tables = read_csv_tables(file_path, header_row_idx)
    return tables[0] if tables else RawTable(rows=[], periods=[], name="csv")


tool("csv.read", allowed_agents=["extractor"])(read_csv)
tool("csv.read_tables", allowed_agents=["extractor"])(read_csv_tables)
tool("csv.read_grid", allowed_agents=["extractor"])(read_csv_grid)


def sniff_csv_headers(file_path: str) -> list[str]:
    grid = read_csv_grid(file_path, max_rows=5)
    header_idx = detect_header_row_heuristic(grid) if grid else 0
    if header_idx is None or header_idx >= len(grid):
        header_idx = 0
    return [h.strip() for h in grid[header_idx] if h.strip()] if grid else []


_BANK_COLUMN_ALIASES = {
    "date": ["date", "txn date", "txn_date", "transaction date", "value date", "tran date",
             "trans date", "booking date", "post date", "posting date", "date of transaction"],
    "narration": ["narration", "description", "particulars", "details", "remarks",
                  "transaction remarks", "transaction details", "transaction narration", "memo"],
    "debit": ["debit", "withdrawal", "debit amount", "dr", "withdrawal amt", "withdrawal amount",
              "debit (inr)", "withdrawal (inr)", "dr amount", "dr (inr)", "dr."],
    "credit": ["credit", "deposit", "credit amount", "cr", "deposit amt", "deposit amount",
               "credit (inr)", "deposit (inr)", "cr amount", "cr (inr)", "cr."],
    "balance": ["balance", "closing balance", "running balance", "closing bal", "balance (inr)",
                "net balance", "account balance", "bal", "bal (inr)"],
    "amount": ["amount", "txn amount", "net amount", "transaction amount"],
    "type": ["type", "dr/cr", "cr/dr", "txn type", "transaction type"],
}


def _find_column(header_norm: list[str], aliases: list[str]) -> int | None:
    for alias in aliases:
        if alias in header_norm:
            return header_norm.index(alias)
    for alias in aliases:
        for idx, col in enumerate(header_norm):
            if alias in col.split() or col == alias:
                return idx
    return None


def _find_bank_header_row(grid: list[list[str]], max_scan: int = 15) -> int:
    """Scans for the header row with the highest match count against bank aliases."""
    best_idx, best_hits = 0, -1
    for i, row in enumerate(grid[:max_scan]):
        header_norm = [c.strip().lower() for c in row if c]
        hits = sum(1 for aliases in _BANK_COLUMN_ALIASES.values() if _find_column(header_norm, aliases) is not None)
        if hits > best_hits:
            best_idx, best_hits = i, hits
    return best_idx if best_hits >= 2 else 0


def read_bank_csv(file_path: str) -> list[dict]:
    rows = _read_grid(file_path)
    if not rows:
        return []

    header_idx = _find_bank_header_row(rows)
    header = rows[header_idx]
    header_norm = [h.strip().lower() for h in header]
    cols = {key: _find_column(header_norm, aliases) for key, aliases in _BANK_COLUMN_ALIASES.items()}

    def cell(row: list[str], key: str) -> str:
        idx = cols.get(key)
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    has_debit_credit = cols.get("debit") is not None or cols.get("credit") is not None
    amount_col = cols.get("amount")
    type_col = cols.get("type")

    transactions = []
    for i, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(c.strip() for c in row):
            continue

        txn_date = cell(row, "date")
        narration = cell(row, "narration")
        if not txn_date and not narration:
            continue

        if has_debit_credit:
            debit = clean_numeric(cell(row, "debit")) or 0.0
            credit = clean_numeric(cell(row, "credit")) or 0.0
        elif amount_col is not None and amount_col < len(row):
            amt = clean_numeric(row[amount_col]) or 0.0
            t_val = cell(row, "type").lower() if type_col is not None else ""
            if "dr" in t_val or amt < 0:
                debit, credit = abs(amt), 0.0
            else:
                debit, credit = 0.0, abs(amt)
        else:
            debit, credit = 0.0, 0.0

        bal_val = clean_numeric(cell(row, "balance")) if cols.get("balance") is not None else None

        transactions.append({
            "row_idx": i,
            "txn_date": txn_date,
            "narration": narration,
            "debit": debit,
            "credit": credit,
            "balance": bal_val,
            "source_ref": {"row": i},
        })
    return transactions


tool("csv.read_bank", allowed_agents=["extractor"])(read_bank_csv)

