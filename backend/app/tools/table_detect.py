"""Detects which row is the real header/column-labels row for a financial-statement table.

Real documents frequently carry metadata above the table (company name, report title,
"(All amounts in INR Lakhs)") and sometimes footnotes below it -- assuming row/line 0 is
always the header breaks on real-world files. This is deliberately a two-stage approach:
a deterministic heuristic first (cheap, no LLM call, handles the common case), and only a
LLM call when the heuristic can't find a confident candidate (see extractor.py) -- keeping
the "deterministic first, LLM as fallback" principle rather than calling the LLM for every
single table.
"""
from __future__ import annotations

from app.tools.parsers.structure import clean_numeric
from app.tools.registry import tool


def _looks_numeric(cell) -> bool:
    return clean_numeric(cell) is not None


def _is_numeric_data_cell(cell) -> bool:
    if cell in (None, ""):
        return False
    # Check if 4-digit year: valid period header, not data cell
    if isinstance(cell, int) and 1900 <= cell <= 2100:
        return False
    s = str(cell).strip()
    if s.isdigit() and len(s) == 4 and 1900 <= int(s) <= 2100:
        return False
    val = clean_numeric(cell)
    return val is not None


def detect_header_row_heuristic(grid: list[list], max_scan: int = 15) -> int | None:
    """grid: raw rows (any cell type, as read straight from the file -- no header assumed).
    Returns the 0-indexed row number of the likely header/column-labels row, or None if
    nothing in the first `max_scan` rows looks confident enough.

    Handles real-world financial statements where:
    1. Candidate periods must not be raw numeric data values (e.g. 109059.93).
    2. Cell A1 in the header may be blank/empty while periods are in subsequent columns.
    3. The header may be followed by section headers (e.g. 'ASSETS', '(A) Operating activities')
       before the first numeric row appears -- looks ahead up to 6 rows.
    """
    scan = grid[:max_scan]
    for i in range(len(scan) - 1):
        row = scan[i]
        if not row or not any(c not in (None, "") for c in row):
            continue
        candidate_periods = [c for c in row[1:] if c not in (None, "")]
        if not candidate_periods:
            continue
        if all(_is_numeric_data_cell(c) for c in candidate_periods):
            continue

        # Look ahead up to 6 rows for at least one data row under candidate columns
        for offset in range(1, min(7, len(scan) - i)):
            next_row = scan[i + offset]
            if not next_row:
                continue
            next_values = next_row[1:1 + len(candidate_periods)] if len(next_row) > 1 else next_row
            if any(_looks_numeric(v) for v in next_values):
                return i
    return None


tool("table.detect_header_row", allowed_agents=["extractor"])(detect_header_row_heuristic)
