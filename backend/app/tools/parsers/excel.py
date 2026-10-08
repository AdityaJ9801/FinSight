"""Excel parsing via openpyxl directly (not pandas) so we keep cell coordinates for
provenance and formatting hints (indentation, bold) for subtotal detection (design doc
§6.4: "openpyxl (merged cells, indentation level, bold = subtotal hint)").

Processes EVERY sheet in the workbook, not just the first -- a single workbook commonly
carries P&L/BS/CF as separate sheets, each needing its own header-row detection since
metadata blocks (and their length) vary sheet to sheet.
"""
from __future__ import annotations

import re
import openpyxl

from app.tools.parsers import RawRow, RawTable
from app.tools.parsers.structure import (
    SectionTracker, clean_numeric, is_columnar_dataset,
    leading_indent, parse_columnar_dataset, period_like
)
from app.tools.parsers.csv_tool import _BANK_COLUMN_ALIASES, _find_bank_header_row, _find_column
from app.tools.registry import tool
from app.tools.table_detect import detect_header_row_heuristic


def _value_grid(rows) -> list[list]:
    return [[c.value for c in row] for row in rows]


def _string_grid(rows) -> list[list[str]]:
    return [[str(c.value) if c.value is not None else "" for c in row] for row in rows]


def read_excel_grid(file_path: str, max_rows: int = 30) -> dict[str, list[list]]:
    """Raw cell-value preview per sheet, no header assumed -- used for header-row
    detection (heuristic or LLM) before the real parse."""
    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    try:
        return {ws.title: _value_grid(list(ws.iter_rows(max_row=max_rows))) for ws in wb.worksheets}
    finally:
        wb.close()


def _build_sheet_table(rows, header_row_idx: int, sheet_name: str) -> RawTable | None:
    if header_row_idx < 0 or header_row_idx >= len(rows):
        header_row_idx = 0
    header_row = rows[header_row_idx]
    # (column index, period header) for the table currently being read. A later sub-table
    # header row can replace it (new period columns) or suspend it (non-period columns).
    active_cols = [(j, str(c.value).strip()) for j, c in enumerate(header_row) if j > 0 and c.value not in (None, "")]
    periods = [p for _, p in active_cols]
    if not periods:
        return None

    sections = SectionTracker()
    raw_rows: list[RawRow] = []
    for row in rows[header_row_idx + 1:]:
        label_cell = row[0]
        if label_cell.value in (None, ""):
            continue
        raw_label = str(label_cell.value)
        label = raw_label.strip()
        try:
            align_indent = int(label_cell.alignment.indent or 0) if label_cell.alignment else 0
        except (TypeError, ValueError):
            align_indent = 0
        indent = align_indent * 2 + leading_indent(raw_label)

        other_cells = [c.value for c in row[1:] if c.value not in (None, "")]
        numeric_cells = [v for v in other_cells if clean_numeric(v) is not None]
        if other_cells and not numeric_cells:
            text_cells = [str(v).strip() for v in other_cells if str(v).strip()]
            is_subtable = len(text_cells) >= 2 and all(re.search(r"[a-zA-Z]", v) for v in text_cells)
            if is_subtable:
                if any(period_like(v) for v in text_cells):
                    active_cols = [(j, str(c.value).strip()) for j, c in enumerate(row)
                                   if j > 0 and c.value not in (None, "") and period_like(c.value)]
                else:
                    active_cols = []
            sections.heading(label, indent)
            continue
        if not other_cells:
            sections.heading(raw_label, indent)  # value-less row: a heading for the rows below
            continue
        if not active_cols:
            continue

        values: dict[str, float] = {}
        for j, period in active_cols:
            if j >= len(row) or row[j].value is None:
                continue
            v = clean_numeric(row[j].value)
            if v is not None:
                values[period] = v
        if not values:
            continue

        section = sections.data_row(raw_label, indent)
        is_bold = bool(label_cell.font and label_cell.font.bold)
        raw_rows.append(RawRow(
            row_idx=label_cell.row, label=label, values=values,
            is_subtotal=is_bold, indent_level=indent, section=section,
            source_ref={"sheet": sheet_name, "cell": label_cell.coordinate, "label": label, "section": section},
        ))

    return RawTable(rows=raw_rows, periods=periods, name=sheet_name) if raw_rows else None


def read_excel(file_path: str, header_overrides: dict[str, int] | None = None) -> dict[str, dict]:
    """Returns {sheet_name: {"table": RawTable, "header_row_idx": int, "confident": bool}}
    for every sheet that yields usable data. `confident=False` means the deterministic
    heuristic couldn't find the header row and row 0 was used as a fallback.
    For columnar sheets, yields both summary and records tables.
    """
    header_overrides = header_overrides or {}
    wb = openpyxl.load_workbook(file_path, data_only=True)
    try:
        results: dict[str, dict] = {}
        for ws in wb.worksheets:
            rows = list(ws.iter_rows())
            if len(rows) < 2:
                continue

            str_grid = _string_grid(rows)

            if ws.title in header_overrides:
                header_idx, confident = header_overrides[ws.title], True
            else:
                detected = detect_header_row_heuristic(_value_grid(rows))
                header_idx, confident = (detected, True) if detected is not None else (0, False)

            # Check if this sheet is a columnar/tabular transaction or metrics dataset
            if is_columnar_dataset(str_grid, header_idx):
                col_tables = parse_columnar_dataset(str_grid, header_idx, name=ws.title)
                for tbl in col_tables:
                    results[tbl.name] = {"table": tbl, "header_row_idx": header_idx, "confident": confident}
                continue

            table = _build_sheet_table(rows, header_idx, ws.title)
            if table is not None:
                results[ws.title] = {"table": table, "header_row_idx": header_idx, "confident": confident}
        return results
    finally:
        wb.close()


def read_bank_excel(file_path: str) -> list[dict]:
    """Reads bank statement transactions from an Excel workbook (.xlsx/.xls)."""
    wb = openpyxl.load_workbook(file_path, data_only=True)
    try:
        best_sheet_rows = []
        for ws in wb.worksheets:
            rows = list(ws.iter_rows())
            if len(rows) > len(best_sheet_rows):
                best_sheet_rows = rows
        if not best_sheet_rows:
            return []

        grid = _string_grid(best_sheet_rows)
        header_idx = _find_bank_header_row(grid)
        header = grid[header_idx]
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
        for i, row in enumerate(grid[header_idx + 1:], start=header_idx + 2):
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

            balance = clean_numeric(cell(row, "balance")) or 0.0
            transactions.append({
                "txn_date": txn_date,
                "narration": narration,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "source_ref": {"row": i, "sheet": ws.title},
            })
        return transactions
    finally:
        wb.close()


tool("excel.read_sheets", allowed_agents=["extractor"])(read_excel)
tool("excel.read_grid", allowed_agents=["extractor"])(read_excel_grid)
tool("excel.read_bank", allowed_agents=["extractor"])(read_bank_excel)
