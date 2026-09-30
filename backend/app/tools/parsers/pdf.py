from __future__ import annotations

import pdfplumber

from app.tools.parsers import RawRow, RawTable
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


def extract_pdf_tables(file_path: str) -> list[RawTable]:
    """Extracts every table pdfplumber finds on every page -- a multi-statement PDF (P&L,
    BS, CF as separate tables/pages in one file) is common, not the single-table case. Each
    table gets its own header-row detection: pdfplumber sometimes captures a units/title
    row as part of the table grid, so row 0 isn't always the real column-header row.
    """
    tables: list[RawTable] = []
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            for table_idx, raw in enumerate(page.extract_tables() or []):
                if len(raw) < 2:
                    continue
                grid = [[str(c).strip() if c is not None else None for c in row] for row in raw]
                header_idx = detect_header_row_heuristic(grid)
                if header_idx is None:
                    header_idx = 0
                header = grid[header_idx]
                periods = [c for c in header[1:] if c]
                if not periods:
                    continue
                raw_rows: list[RawRow] = []
                for r_idx, row in enumerate(grid[header_idx + 1:], start=1):
                    if not row or not row[0]:
                        continue
                    label = row[0]
                    values: dict[str, float] = {}
                    for j, period in enumerate(periods):
                        if j + 1 >= len(row) or row[j + 1] is None:
                            continue
                        try:
                            values[period] = float(row[j + 1].replace(",", ""))
                        except ValueError:
                            continue
                    if not values:
                        continue  # footnote/note row, not real data
                    raw_rows.append(RawRow(
                        row_idx=r_idx, label=label, values=values,
                        source_ref={"page": page_num, "table": table_idx},
                    ))
                if raw_rows:
                    tables.append(RawTable(rows=raw_rows, periods=periods, name=f"page{page_num}_table{table_idx}"))
    return tables


tool("pdf.extract_text", allowed_agents=["intake_classifier", "extractor"])(extract_pdf_text)
tool("pdf.extract_tables", allowed_agents=["extractor"])(extract_pdf_tables)
