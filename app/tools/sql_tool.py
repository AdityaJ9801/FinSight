"""Read-only query tool for the QA agent (design doc §6.9: "text-to-SQL on allow-listed
views... tenant/entity filters added by code, not by the LLM").

Simplification vs. the design doc: instead of the LLM generating raw SQL text (which would
need a full SQL-injection-safe validator), the LLM/router only chooses a `view` name and a
`filters` dict of {allow-listed column: value}; this module composes the actual
parameterized SQL. This gets the same guarantee -- the model can never express a query
outside the allow-listed views/columns -- with far less surface area to get wrong.
"""
from __future__ import annotations

from sqlalchemy import text

from app.extensions import db
from app.tools.registry import ToolError, tool

ALLOWED_VIEWS: dict[str, set[str]] = {
    "v_metrics": {"dataset_version", "metric_code", "period_end"},
    "v_findings": {"dataset_version", "module", "severity"},
    "v_statements_wide": {"dataset_version", "account_id", "period_end"},
    "v_bank_monthly": {"dataset_version"},
}


def query_readonly(view: str, filters: dict | None = None, limit: int = 100) -> list[dict]:
    if view not in ALLOWED_VIEWS:
        raise ToolError(f"view '{view}' is not allow-listed for read-only queries")

    allowed_cols = ALLOWED_VIEWS[view]
    where_clauses = []
    params: dict = {}
    for col, val in (filters or {}).items():
        if col not in allowed_cols:
            raise ToolError(f"filter column '{col}' is not allowed for view '{view}'")
        where_clauses.append(f"{col} = :{col}")
        params[col] = val

    limit = min(int(limit), 500)
    sql = f"SELECT * FROM {view}"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += f" LIMIT {limit}"

    result = db.session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


tool("sql.query_readonly", allowed_agents=["ratio", "cash_wc", "gst", "qa", "verifier"])(query_readonly)
