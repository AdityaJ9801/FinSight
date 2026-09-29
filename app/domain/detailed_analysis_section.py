"""The report's "Detailed Statement Analysis" tables section.

Built deterministically from the DetailedAnalyticsAgent's blackboard artifact
(`detailed_analysis`), the same way the Data Diagnostic section is built from the database:
every figure is formatted from computed values, none is typed by an LLM, so it's appended
after verification rather than going through the placeholder verifier.

Returns renderer-neutral data (tables of already-formatted strings) that the HTML, DOCX and
PDF renderers each lay out, plus a plain-text `body` fallback.
"""
from __future__ import annotations

from typing import Any

from app.orchestrator import blackboard
from app.tools.report_render import format_indian_number
from app.utils.money import display_scale_for, set_thread_scale, thread_scale

SECTION_KEY = "detailed_analysis_tables"
HEADING = "Detailed Statement Analysis — Supporting Tables"

_PL_LINES = ["PL.REVENUE", "PL.OTHER_INCOME", "PL.COGS", "PL.EMPLOYEE_COST", "PL.OTHER_EXPENSES",
             "PL.DEPRECIATION", "PL.FINANCE_COST", "PL.PBT", "PL.TAX", "PL.PAT"]
_BS_LINES = ["BS.CA.CASH", "BS.CA.TRADE_RECEIVABLES", "BS.CA.INVENTORY", "BS.CA.TOTAL", "BS.NCA.PPE",
             "BS.CL.TRADE_PAYABLES", "BS.CL.SHORT_TERM_BORROWINGS", "BS.CL.TOTAL", "BS.NCL.LONG_TERM_BORROWINGS",
             "BS.EQ.TOTAL"]


def _amt(v) -> str:
    return "—" if v is None else format_indian_number(float(v), "INR")


def _pct(v) -> str:
    return "—" if v is None else format_indian_number(float(v), "%")


def _x(v) -> str:
    return "—" if v is None else format_indian_number(float(v), "x")


def _signed_amt(v) -> str:
    if v is None:
        return "—"
    return ("+" if v > 0 else "") + format_indian_number(float(v), "INR").replace("Rs -", "-Rs ")


def _table(title: str, columns: list[str], rows: list[list[str]], note: str | None = None) -> dict:
    return {"title": title, "columns": columns, "rows": rows, "note": note}


def _statement_tables(analysis: dict) -> list[dict]:
    periods = analysis.get("periods", [])
    stmts = analysis.get("statements") or {}
    tables = []
    pl = {r["account_id"]: r for r in stmts.get("PL", [])}
    if pl and periods:
        latest = periods[-1]
        rows = []
        for acc in _PL_LINES:
            r = pl.get(acc)
            if not r:
                continue
            rows.append([r["account_name"], *(_amt(r["values"].get(p)) for p in periods),
                         _pct(r["change_pct"].get(latest)) if len(periods) > 1 else "—"])
        tables.append(_table("Horizontal analysis — Profit & Loss", ["Line item", *periods, f"YoY % ({latest})"], rows,
                             "Each line's value by period and its change in the latest period."))
        cs_rows = []
        for acc in _PL_LINES:
            r = pl.get(acc)
            if r and any(r["common_size"].get(p) is not None for p in periods):
                cs_rows.append([r["account_name"], *(_pct(r["common_size"].get(p)) for p in periods)])
        if cs_rows:
            tables.append(_table("Common-size P&L — % of revenue", ["Line item", *periods], cs_rows,
                                 "Vertical analysis: cost lines rising as a share of revenue compress margins."))
    bs = {r["account_id"]: r for r in stmts.get("BS", [])}
    if bs and periods:
        rows = [[bs[a]["account_name"], *(_pct(bs[a]["common_size"].get(p)) for p in periods)]
                for a in _BS_LINES if a in bs and any(bs[a]["common_size"].get(p) is not None for p in periods)]
        if rows:
            tables.append(_table("Balance sheet composition — % of total assets", ["Line item", *periods], rows))
    return tables


def _analysis_tables(analysis: dict) -> list[dict]:
    tables = []
    if analysis.get("dupont"):
        tables.append(_table("DuPont decomposition of ROE",
                             ["Period", "Net margin", "Asset turnover", "Equity multiplier", "ROE"],
                             [[d["period"], _pct(d["net_margin"]), _x(d["asset_turnover"]), _x(d["equity_multiplier"]),
                               _pct(d["roe"])] for d in analysis["dupont"]],
                             "ROE = net margin × asset turnover × equity multiplier."))
    if analysis.get("growth"):
        tables.append(_table("Compound annual growth (CAGR)", ["Series", "From", "To", "Start", "End", "Years", "CAGR"],
                             [[g["label"], g["first_period"], g["last_period"], _amt(g["first"]), _amt(g["last"]),
                               f"{g['years']:.2f}", _pct(g["cagr"])] for g in analysis["growth"]],
                             "CAGR is left blank where a start or end value is not positive."))
    bridge = analysis.get("profit_bridge")
    if bridge:
        rows = []
        for s in bridge["steps"]:
            rows.append([s["label"], _amt(s["amount"]) if s["kind"] in ("start", "end") else _signed_amt(s["amount"])])
        note = "Each line's change, signed by its effect on PAT."
        if bridge.get("reconciled") is False:
            note += (" ⚠ The P&L does not reconcile for these periods, so part of the PAT movement is shown as an "
                     "unreconciled difference -- see the Data Diagnostic's P&L checks for where the gap sits.")
        tables.append(_table(f"Profit bridge — PAT {bridge['from_period']} → {bridge['to_period']}", ["Step", "PAT impact"],
                             rows, note))
    if analysis.get("leverage_liquidity"):
        tables.append(_table("Working capital & net debt", ["Period", "Working capital", "Total debt", "Net debt",
                                                            "Net debt / EBITDA"],
                             [[r["period"], _amt(r["working_capital"]), _amt(r["total_debt"]), _amt(r["net_debt"]),
                               _x(r["net_debt_to_ebitda"])] for r in analysis["leverage_liquidity"]]))
    bank = analysis.get("bank") or {}
    if bank.get("monthly"):
        tables.append(_table("Bank statement — monthly cash flows", ["Month", "Inflows", "Outflows", "Net", "Closing balance"],
                             [[m["month"], _amt(m["inflow"]), _amt(m["outflow"]), _signed_amt(m["net"]),
                               _amt(m["closing_balance"])] for m in bank["monthly"]]))
        cp_rows = [["Inflow", c["counterparty"], _amt(c["amount"]), _pct(c["share"])] for c in bank.get("top_inflows", [])[:3]]
        cp_rows += [["Outflow", c["counterparty"], _amt(c["amount"]), _pct(c["share"])] for c in bank.get("top_outflows", [])[:3]]
        if cp_rows:
            tables.append(_table("Bank statement — top counterparties", ["Direction", "Narration", "Amount", "Share"],
                                 cp_rows, "Concentration check: a single payer/payee dominating flows warrants review."))
    return tables


def build_detailed_analysis_section(job_id: str) -> dict[str, Any] | None:
    analysis = blackboard.read(job_id, "detailed_analysis")
    if not analysis:
        return None
    # Amounts in the source document's unit (crore for a crore filing), same as the charts
    # and narrative -- not full rupees, which read as a 10^7 error next to them.
    from app.extensions import db
    from app.models.job import Job

    job = db.session.get(Job, job_id)
    previous = thread_scale()
    set_thread_scale(display_scale_for(job.dataset_version_id if job else None))
    try:
        tables = _statement_tables(analysis) + _analysis_tables(analysis)
    finally:
        set_thread_scale(previous)
    if not tables:
        return None
    lines = []
    for t in tables:
        lines += ["", t["title"], " | ".join(t["columns"])] + [" | ".join(r) for r in t["rows"]]
    return {
        "heading": HEADING, "section_key": SECTION_KEY, "kind": SECTION_KEY, "chart_ids": [],
        "body": "\n".join(lines).strip(), "tables": tables,
    }
