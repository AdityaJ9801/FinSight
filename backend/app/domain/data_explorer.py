"""Dynamic Data Explorer: extracts, inspects and formats all actual data attributes
present in the dataset into both Row Format (horizontal statement layout) and Column Format
(tabular layout with attributes as columns and periods/records as rows).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.domain.coa import CANONICAL_ACCOUNTS
from app.extensions import db
from app.models.dataset import DatasetVersion, FinancialFact
from app.models.document import Document
from app.models.job import Job
from app.tools.report_render import format_indian_number

ACCOUNT_NAMES = {acc_id: name for acc_id, name, _, _, _ in CANONICAL_ACCOUNTS}
ACCOUNT_ORDER = {acc_id: i for i, (acc_id, *_rest) in enumerate(CANONICAL_ACCOUNTS)}

STATEMENT_DISPLAY_NAMES = {
    "PL": "Profit & Loss",
    "BS": "Balance Sheet",
    "CF": "Cash Flow",
    "P&L Statement": "Profit & Loss",
    "Balance Sheet": "Balance Sheet",
    "Cash Flow Statement": "Cash Flow",
}


def _pct_change(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev in (None, 0):
        return None
    return (curr - prev) / abs(prev)


def inspect_dataset_attributes(job_id: str, dataset_version_id: str | None = None) -> dict[str, Any]:
    """Inspects the actual financial facts in the database and generates dynamic
    Row-format and Column-format attribute structures based entirely on what is in the data.
    """
    if not dataset_version_id:
        job = db.session.get(Job, job_id)
        if not job or not job.dataset_version_id:
            return {"error": "No dataset version found for job"}
        dataset_version_id = job.dataset_version_id

    facts = FinancialFact.query.filter_by(dataset_version=dataset_version_id).order_by(FinancialFact.period_end).all()
    if not facts:
        return {
            "summary": {"total_attributes": 0, "total_periods": 0, "total_facts": 0, "sheets": []},
            "sheets": [],
            "periods": [],
            "row_format": {},
            "column_format": {},
        }

    # Extract all distinct periods
    periods = sorted(list({f.period_end.isoformat() for f in facts}))

    # Map documents for filename reference
    docs = {d.id: d.original_filename for d in Document.query.filter_by(job_id=job_id).all()}

    # Group facts by attribute key (combining label + canonical account to distinguish lines)
    # Key: (sheet_name, label, account_id)
    attribute_data: dict[tuple[str, str, str], dict[str, Any]] = {}

    for f in facts:
        sheet = (f.source_ref or {}).get("sheet")
        stmt_prefix = f.account_id.split(".", 1)[0]
        if not sheet:
            sheet = STATEMENT_DISPLAY_NAMES.get(stmt_prefix, stmt_prefix)
        else:
            sheet = STATEMENT_DISPLAY_NAMES.get(sheet, sheet)

        label = (f.source_ref or {}).get("label")
        if not label:
            label = ACCOUNT_NAMES.get(f.account_id, f.account_id.replace("_", " ").title())

        key = (sheet, label, f.account_id)
        if key not in attribute_data:
            attribute_data[key] = {
                "label": label,
                "account_id": f.account_id,
                "account_name": ACCOUNT_NAMES.get(f.account_id, f.account_id),
                "statement": stmt_prefix,
                "sheet": sheet,
                "unit": f.currency or "INR",
                "source_doc": docs.get(f.source_doc, "Uploaded Statement"),
                "values": {},
            }
        p_iso = f.period_end.isoformat()
        attribute_data[key]["values"][p_iso] = float(f.value)

    # All unique sheets
    sheet_names = sorted(list({k[0] for k in attribute_data.keys()}))

    # -------------------------------------------------------------
    # 1. BUILD ROW FORMAT (Attributes as rows, periods as columns)
    # -------------------------------------------------------------
    row_format_by_sheet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_row_format: list[dict[str, Any]] = []

    for (sheet, label, acc_id), item in attribute_data.items():
        vals = item["values"]
        # Calculate changes across periods
        change_pct: dict[str, float | None] = {}
        for i, p in enumerate(periods):
            curr = vals.get(p)
            if i > 0:
                prev = vals.get(periods[i - 1])
                change_pct[p] = _pct_change(curr, prev)
            else:
                change_pct[p] = None

        row_item = {
            "attribute_name": label,
            "account_id": acc_id,
            "account_name": item["account_name"],
            "sheet": sheet,
            "unit": item["unit"],
            "source_doc": item["source_doc"],
            "values": {p: vals.get(p) for p in periods},
            "change_pct": change_pct,
            "order_index": ACCOUNT_ORDER.get(acc_id, 999),
        }
        row_format_by_sheet[sheet].append(row_item)
        all_row_format.append(row_item)

    # Sort rows by account order and label
    for s in row_format_by_sheet:
        row_format_by_sheet[s].sort(key=lambda r: (r["order_index"], r["attribute_name"]))
    all_row_format.sort(key=lambda r: (r["order_index"], r["attribute_name"]))

    # -------------------------------------------------------------
    # 2. BUILD COLUMN FORMAT (Periods as rows, attributes as columns)
    # -------------------------------------------------------------
    column_format_by_sheet: dict[str, dict[str, Any]] = {}

    for s, rows in row_format_by_sheet.items():
        # Columns definition
        columns = [
            {"key": "period", "label": "Period End", "type": "date"},
        ]
        seen_attr_keys = set()
        for r in rows:
            attr_key = f"{r['account_id']}::{r['attribute_name']}"
            if attr_key not in seen_attr_keys:
                seen_attr_keys.add(attr_key)
                columns.append({
                    "key": attr_key,
                    "label": r["attribute_name"],
                    "account_id": r["account_id"],
                    "type": "numeric",
                    "unit": r["unit"],
                })

        # Rows per period
        table_rows = []
        for p in periods:
            period_row: dict[str, Any] = {"period": p}
            has_any_data = False
            for r in rows:
                attr_key = f"{r['account_id']}::{r['attribute_name']}"
                v = r["values"].get(p)
                period_row[attr_key] = v
                if v is not None:
                    has_any_data = True
            if has_any_data:
                table_rows.append(period_row)

        column_format_by_sheet[s] = {
            "columns": columns,
            "rows": table_rows,
            "total_attributes": len(columns) - 1,
            "total_periods": len(table_rows),
        }

    # Combined "All Data" in Column Format
    all_columns = [{"key": "period", "label": "Period End", "type": "date"}]
    seen_all = set()
    for r in all_row_format:
        attr_key = f"{r['sheet']}::{r['attribute_name']}"
        if attr_key not in seen_all:
            seen_all.add(attr_key)
            all_columns.append({
                "key": attr_key,
                "label": f"[{r['sheet']}] {r['attribute_name']}",
                "account_id": r["account_id"],
                "type": "numeric",
                "unit": r["unit"],
            })
    all_table_rows = []
    for p in periods:
        period_row = {"period": p}
        for r in all_row_format:
            attr_key = f"{r['sheet']}::{r['attribute_name']}"
            period_row[attr_key] = r["values"].get(p)
        all_table_rows.append(period_row)

    column_format_by_sheet["All Attributes"] = {
        "columns": all_columns,
        "rows": all_table_rows,
        "total_attributes": len(all_columns) - 1,
        "total_periods": len(all_table_rows),
    }

    sheets_list = ["All Attributes"] + [s for s in sheet_names if s != "All Attributes"]

    return {
        "summary": {
            "total_attributes": len(attribute_data),
            "total_periods": len(periods),
            "total_facts": len(facts),
            "sheets": sheets_list,
        },
        "sheets": sheets_list,
        "periods": periods,
        "row_format": {
            "sheets": row_format_by_sheet,
            "all": all_row_format,
        },
        "column_format": {
            "sheets": column_format_by_sheet,
        },
    }
