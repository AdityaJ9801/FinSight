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

from app.tools.registry import tool


def _looks_numeric(cell) -> bool:
    if cell in (None, ""):
        return False
    s = str(cell).strip().replace(",", "")
    if s.startswith("(") and s.endswith(")") and len(s) > 2:
        s = "-" + s[1:-1]
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _is_numeric_data_cell(cell) -> bool:
    if cell in (None, ""):
        return False
    if isinstance(cell, (int, float)):
        # 4-digit years between 1900 and 2100 are valid headers
        if isinstance(cell, int) and 1900 <= cell <= 2100:
            return False
        return True
    s = str(cell).strip().replace(",", "")
    if s.startswith("(") and s.endswith(")") and len(s) > 2:
        return True
    try:
        f = float(s)
        if "." in s or f < 1900 or f > 2100:
            return True
    except ValueError:
        pass
    return False


def detect_header_row_heuristic(grid: list[list], max_scan: int = 15) -> int | None:
    """grid: raw rows (any cell type, as read straight from the file -- no header assumed).
    Returns the 0-indexed row number of the likely header/column-labels row, or None if
    nothing in the first `max_scan` rows looks confident enough.

    Handles real-world financial statements where:
    1. Candidate periods must not be raw numeric data values (e.g. 109059.93).
    2. The header may be followed by section headers (e.g. 'ASSETS', '(A) Operating activities')
       before the first numeric row appears -- looks ahead up to 6 rows.
    """
    scan = grid[:max_scan]
    for i in range(len(scan) - 1):
        row = scan[i]
        if not row or row[0] in (None, ""):
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
            next_values = next_row[1:1 + len(candidate_periods)]
            if any(_looks_numeric(v) for v in next_values):
                return i
    return None


tool("table.detect_header_row", allowed_agents=["extractor"])(detect_header_row_heuristic)
