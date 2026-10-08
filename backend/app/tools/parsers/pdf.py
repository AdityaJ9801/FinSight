from __future__ import annotations

import re
import pdfplumber

from app.tools.parsers import RawRow, RawTable
from app.tools.parsers.structure import (
    clean_numeric, is_columnar_dataset, parse_columnar_dataset, period_like
)
from app.tools.registry import tool
from app.tools.table_detect import detect_header_row_heuristic


def extract_pdf_text(file_path: str, max_pages: int = 3) -> str:
    """First few pages of text -- enough for intake classification without loading the
    whole document (design doc §6.2: "page-level text for one chunk of a long PDF")."""
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages[:max_pages]:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def is_scanned_pdf(file_path: str) -> bool:
    text = extract_pdf_text(file_path, max_pages=2)
    return len(text.strip()) < 20  # essentially no digital text layer


def _parse_grid_to_tables(grid: list[list[str]], name: str) -> list[RawTable]:
    if len(grid) < 2:
        return []

    header_idx = detect_header_row_heuristic(grid)
    if header_idx is None:
        header_idx = 0

    if is_columnar_dataset(grid, header_idx):
        return parse_columnar_dataset(grid, header_idx, name=name)

    header = grid[header_idx]
    active_cols = [(j, str(c).strip()) for j, c in enumerate(header) if j > 0 and c]
    periods = [p for _, p in active_cols]
    if not periods:
        return []

    raw_rows: list[RawRow] = []
    for r_idx, row in enumerate(grid[header_idx + 1:], start=1):
        if not row or not str(row[0]).strip():
            continue
        label = str(row[0]).strip()
        values: dict[str, float] = {}
        for j, period in active_cols:
            if j >= len(row) or row[j] is None:
                continue
            val = clean_numeric(row[j])
            if val is not None:
                values[period] = val

        if not values:
            continue
        raw_rows.append(RawRow(
            row_idx=r_idx, label=label, values=values,
            source_ref={"table": name, "row": r_idx},
        ))

    return [RawTable(rows=raw_rows, periods=periods, name=name)] if raw_rows else []


def _extract_text_table_fallback(text: str, name: str) -> list[RawTable]:
    """Fallback when pdfplumber table extraction finds no border/text tables:
    parses aligned digital text lines where lines have a label followed by 1+ numbers."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return []

    # Try to find a header line with period-like strings
    header_idx = -1
    periods: list[str] = []
    for i, line in enumerate(lines[:10]):
        tokens = re.split(r"\s{2,}|\t", line)
        if len(tokens) >= 2:
            p_candidates = [t for t in tokens[1:] if period_like(t)]
            if len(p_candidates) >= 1:
                header_idx = i
                periods = [t.strip() for t in tokens[1:] if t.strip()]
                break

    if not periods:
        return []

    raw_rows: list[RawRow] = []
    for r_idx, line in enumerate(lines[header_idx + 1:], start=1):
        tokens = re.split(r"\s{2,}|\t", line)
        if len(tokens) < 2:
            continue
        label = tokens[0].strip()
        values: dict[str, float] = {}
        for j, p in enumerate(periods):
            if j + 1 < len(tokens):
                num = clean_numeric(tokens[j + 1])
                if num is not None:
                    values[p] = num
        if values:
            raw_rows.append(RawRow(
                row_idx=r_idx, label=label, values=values,
                source_ref={"table": name, "row": r_idx},
            ))

    return [RawTable(rows=raw_rows, periods=periods, name=name)] if raw_rows else []


def extract_pdf_tables(file_path: str) -> list[RawTable]:
    """Extracts every table pdfplumber finds on every page, with fallback to borderless
    strategy and text-line parsing."""
    tables: list[RawTable] = []
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            raw_tables = page.extract_tables() or []

            # If no bordered tables found, try borderless table extraction strategy
            if not raw_tables:
                raw_tables = page.extract_tables(table_settings={
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "snap_tolerance": 4,
                }) or []

            if raw_tables:
                for table_idx, raw in enumerate(raw_tables):
                    grid = [[str(c).strip() if c is not None else "" for c in row] for row in raw]
                    parsed = _parse_grid_to_tables(grid, name=f"page{page_num}_table{table_idx}")
                    tables.extend(parsed)
            else:
                # Text line fallback
                page_text = page.extract_text() or ""
                parsed = _extract_text_table_fallback(page_text, name=f"page{page_num}_text_table")
                tables.extend(parsed)

    return tables


tool("pdf.extract_text", allowed_agents=["intake_classifier", "extractor"])(extract_pdf_text)
tool("pdf.extract_tables", allowed_agents=["extractor"])(extract_pdf_tables)
