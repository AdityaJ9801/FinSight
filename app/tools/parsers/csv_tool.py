from __future__ import annotations

import csv as _csv

from app.tools.parsers import RawRow, RawTable
from app.tools.registry import tool
from app.tools.table_detect import detect_header_row_heuristic


_CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]


def _guess_delimiter(sample: str) -> str:
    """csv.Sniffer gets confused when a metadata preamble (company name, report title --
    lines with few or no delimiters) precedes the real table, sometimes guessing a
    delimiter from a stray character in that preamble instead. Counting delimiter
    occurrences across the whole sample is more robust to that than Sniffer's heuristics."""
    counts = {d: sample.count(d) for d in _CANDIDATE_DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _read_grid(file_path: str) -> list[list[str]]:
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(8192)
        f.seek(0)
        delimiter = _guess_delimiter(sample)
        reader = _csv.reader(f, delimiter=delimiter)
        return list(reader)


def read_csv_grid(file_path: str, max_rows: int = 30) -> list[list[str]]:
    """Raw rows, no header assumed -- used for header-row detection (heuristic or LLM)."""
    return _read_grid(file_path)[:max_rows]


def build_table_from_grid(grid: list[list[str]], header_row_idx: int, name: str = "csv") -> RawTable:
    if header_row_idx < 0 or header_row_idx >= len(grid):
        header_row_idx = 0
    header = grid[header_row_idx]
    periods = [c.strip() for c in header[1:] if c.strip()]

    raw_rows: list[RawRow] = []
    for i, row in enumerate(grid[header_row_idx + 1:], start=header_row_idx + 2):
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        values: dict[str, float] = {}
        for j, period in enumerate(periods):
            if j + 1 >= len(row):
                break
            raw_val = row[j + 1].strip().replace(",", "")
            if not raw_val:
                continue
            try:
                values[period] = float(raw_val)
            except ValueError:
                continue
        if not values:
            # A label with no numeric values under any period column is more likely a
            # footnote/note line than a real data row (design constraint: files carry
            # trailing metadata too, not just leading).
            continue
        raw_rows.append(RawRow(row_idx=i, label=label, values=values, source_ref={"row": i}))

    return RawTable(rows=raw_rows, periods=periods, name=name)


def read_csv(file_path: str, header_row_idx: int | None = None) -> RawTable:
    """header_row_idx: pass an explicit value (e.g. LLM-chosen, see extractor.py) to skip
    detection; otherwise runs the deterministic heuristic and falls back to row 0."""
    grid = _read_grid(file_path)
    if len(grid) < 2:
        return RawTable(rows=[], periods=[], name="csv")
    if header_row_idx is None:
        header_row_idx = detect_header_row_heuristic(grid)
        if header_row_idx is None:
            header_row_idx = 0
    return build_table_from_grid(grid, header_row_idx, name="csv")


tool("csv.read", allowed_agents=["extractor"])(read_csv)
tool("csv.read_grid", allowed_agents=["extractor"])(read_csv_grid)


def sniff_csv_headers(file_path: str) -> list[str]:
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = _csv.reader(f)
        header = next(reader, [])
    return [h.strip() for h in header]


_BANK_COLUMN_ALIASES = {
    "date": ["date", "txn date", "transaction date", "value date"],
    "narration": ["narration", "description", "particulars", "details"],
    "debit": ["debit", "withdrawal", "debit amount", "dr"],
    "credit": ["credit", "deposit", "credit amount", "cr"],
    "balance": ["balance", "closing balance", "running balance"],
}


def _find_column(header_norm: list[str], aliases: list[str]) -> int | None:
    for alias in aliases:
        if alias in header_norm:
            return header_norm.index(alias)
    return None


def _find_bank_header_row(grid: list[list[str]], max_scan: int = 15) -> int:
    """Bank statements often carry a metadata block (account holder, period, IFSC, etc.)
    above the actual transaction table -- scan for the row that most looks like the real
    column-header row instead of assuming row 0."""
    best_idx, best_hits = 0, -1
    for i, row in enumerate(grid[:max_scan]):
        header_norm = [c.strip().lower() for c in row]
        hits = sum(1 for aliases in _BANK_COLUMN_ALIASES.values() if _find_column(header_norm, aliases) is not None)
        if hits > best_hits:
            best_idx, best_hits = i, hits
    return best_idx if best_hits >= 2 else 0  # need at least 2 recognizable columns to trust it


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

    def to_float(val: str) -> float:
        val = val.replace(",", "").strip()
        if not val:
            return 0.0
        try:
            return float(val)
        except ValueError:
            return 0.0

    transactions = []
    for i, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(c.strip() for c in row):
            continue
        transactions.append({
            "row_idx": i,
            "txn_date": cell(row, "date"),
            "narration": cell(row, "narration"),
            "debit": to_float(cell(row, "debit")),
            "credit": to_float(cell(row, "credit")),
            "balance": to_float(cell(row, "balance")) if cell(row, "balance") else None,
            "source_ref": {"row": i},
        })
    return transactions


tool("csv.read_bank", allowed_agents=["extractor"])(read_bank_csv)
