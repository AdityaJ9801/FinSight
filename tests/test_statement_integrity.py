"""Regression tests for statement integrity on realistic Ind AS workbooks.

Guards the failures found when comparing reports across LLMs on a listed company's filing:
P&L that didn't reconcile (exceptional-item sign, purchases lost, capitalised expenditure
ignored), a profit-bridge plug, hundreds of low-confidence guesses, balance-sheet chart shares
contradicting the tables, short-term borrowings lost to a repeated 'Borrowings' label, notes
and schedules summed into statement lines, and unit scale varying by model.

The fixture is a DIFFERENT company from the one the bugs were found on (lakhs not crore,
different captions, an expense caption with no canonical line, notes with non-period
sub-tables) so these tests prove the rules generalise rather than fit one workbook.
"""
import hashlib
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from app.agents.analysis.supervisor import AnalysisSupervisor
from app.agents.data.supervisor import DataSupervisor
from app.agents.delivery.supervisor import DeliverySupervisor
from app.domain.coa import contextual_account, detect_unit_scale, sheet_role
from app.domain.facts import load_facts_by_period
from app.domain.validation_rules import check_pl_cascade, exceptional_effect
from app.extensions import db
from app.llm_gateway import get_llm_gateway
from app.models.document import Document
from app.models.review import ReviewItem
from app.models.tenant import Entity, Tenant
from app.models.validation import ValidationResult
from app.orchestrator import blackboard
from app.orchestrator.orchestrator import create_job
from app.tools.parsers.excel import read_excel
from app.utils import storage
from app.utils.ids import new_id

FY25, FY24 = date(2025, 3, 31), date(2024, 3, 31)
LAKH = 100_000
H = ["Particulars", "As at March 31, 2025", "As at March 31, 2024"]
HY = ["Particulars", "Year ended March 31, 2025", "Year ended March 31, 2024"]

BALANCE_SHEET = [
    ["ASSETS"], ["Non-current assets"],
    ["Property, plant and equipment", 5000, 4600], ["Capital work-in-progress", 400, 700],
    ["Right-of-use assets", 150, 120], ["Financial assets"], ["  Investments", 800, 700],
    ["  Other financial assets", 50, 40], ["Other non-current assets", 100, 90],
    ["Total non-current assets", 6500, 6250],
    ["Current assets"], ["Inventories", 1200, 1100], ["Financial assets"], ["  Trade receivables", 900, 850],
    ["  Cash and cash equivalents", 300, 250], ["  Other balances with banks", 60, 50],
    ["Other current assets", 140, 150], ["Total current assets", 2600, 2400],
    ["TOTAL ASSETS", 9100, 8650],
    ["EQUITY AND LIABILITIES"], ["Equity"], ["Equity share capital", 500, 500], ["Other equity", 4600, 4200],
    ["Total equity", 5100, 4700],
    ["Non-current liabilities"], ["Financial liabilities"], ["  Borrowings", 1500, 1600],
    ["  Lease liabilities", 100, 80], ["Provisions", 150, 140], ["Deferred tax liabilities (net)", 250, 230],
    ["Total non-current liabilities", 2000, 2050],
    ["Current liabilities"], ["Financial liabilities"], ["  Borrowings", 400, 350],
    ["  Trade payables - dues of micro and small enterprises", 200, 180],
    ["  Trade payables - dues of others", 900, 850], ["  Other financial liabilities", 150, 140],
    ["Other current liabilities", 250, 230], ["Provisions", 100, 150],
    ["Total current liabilities", 2000, 1900], ["Total liabilities", 4000, 3950],
    ["TOTAL EQUITY AND LIABILITIES", 9100, 8650],
]
PNL = [
    ["Revenue from operations", 10000, 9000], ["Other income", 200, 150], ["Total income", 10200, 9150],
    ["Expenses:"], ["Cost of materials consumed", 5000, 4600], ["Purchases of stock-in-trade", 600, 500],
    ["Changes in inventories of finished goods, work-in-progress and stock-in-trade", -100, 50],
    ["Employee benefits expense", 1200, 1100], ["Finance costs", 250, 240],
    ["Depreciation and amortisation expense", 400, 380], ["Power and fuel", 500, 450],
    ["Other expenses", 900, 800], ["Less: Expenditure transferred to capital account", 50, 40],
    ["Total expenses", 8700, 8080], ["Profit before exceptional items and tax", 1500, 1070],
    ["Exceptional items:"], ["Impairment of investments", -120, -30], ["Total exceptional items", -120, -30],
    ["Profit before tax", 1380, 1040],
    ["Tax expense:"], ["Current tax", 330, 250], ["Deferred tax", 20, 10], ["Total tax expense", 350, 260],
    ["Profit for the year", 1030, 780],
    ["Other comprehensive income"], ["(a) Remeasurement of defined benefit plans", -10, 5],
    ["Total other comprehensive income for the year", -10, 5], ["Total comprehensive income for the year", 1020, 785],
    ["Earnings per share (Rs)"], ["  Basic", 20.6, 15.6], ["  Diluted", 20.6, 15.6],
]
CASH_FLOW = [
    ["(A) Cash flows from operating activities"], ["Profit before tax", 1380, 1040], ["Adjustments for:"],
    ["Depreciation and amortisation expense", 400, 380], ["Finance costs", 250, 240],
    ["Operating profit before working capital changes", 2030, 1660], ["Inventories", -100, -50],
    ["Net cash from/(used in) operating activities", 1700, 1300],
    ["(B) Cash flows from investing activities"], ["Purchase of capital assets", -800, -900],
    ["Net cash from/(used in) investing activities", -800, -900],
    ["(C) Cash flows from financing activities"], ["Dividend paid", -620, -500], ["Interest paid", -230, 150],
    ["Net cash from/(used in) financing activities", -850, -350],
    ["Net increase/(decrease) in cash and cash equivalents", 50, 50],
    ["Opening cash and cash equivalents", 250, 200], ["Closing cash and cash equivalents", 300, 250],
]
BORROWINGS_NOTE = [
    ["Term loans from banks", 1500, 1600], ["Total non-current borrowings", 1500, 1600],
    ["Working capital loans", 400, 350], ["Total current borrowings", 400, 350],
    [],
    ["Lender", "Rate", "Repayment terms"],  # a sub-table whose columns are NOT periods
    ["Bank A", "9.5%", "Quarterly till 2029"], ["Bank B", "8.9%", "Bullet 2027"],
]
RECEIVABLES_NOTE = [
    ["Considered good", 950, 900], ["Less: Allowance for credit losses", 50, 50],
    ["Total trade receivables (net)", 900, 850],
    [],
    ["Ageing", "Not due", "< 6 months", "6-12 months"],
    ["Undisputed", 600, 250, 100],
]


def _sheet(wb, title, header, rows, unit="(Rs in lakhs)"):
    ws = wb.create_sheet(title)
    ws.append([title.upper()])
    ws.append([f"For the year ended March 31, 2025  |  {unit}"])
    ws.append([])
    ws.append(header)
    for r in rows:
        ws.append(r)


def build_workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Balance Sheet", H, BALANCE_SHEET)
    _sheet(wb, "Statement of Profit and Loss", HY, PNL)
    _sheet(wb, "Cash Flow Statement", HY, CASH_FLOW)
    _sheet(wb, "Borrowings Note", H, BORROWINGS_NOTE)
    _sheet(wb, "Receivables Ageing", H, RECEIVABLES_NOTE)
    wb.save(path)
    return path


@pytest.fixture()
def acme_job(app, tmp_path):
    with app.app_context():
        tenant = Tenant(id=new_id("ten_"), name="T")
        db.session.add(tenant)
        db.session.flush()
        entity = Entity(id=new_id("ent_"), tenant_id=tenant.id, legal_name="Acme")
        db.session.add(entity)
        db.session.commit()
        job = create_job(tenant.id, entity.id, created_by="t", goal="integrity")
        content = build_workbook(tmp_path / "acme.xlsx").read_bytes()
        db.session.add(Document(id=new_id("doc_"), tenant_id=tenant.id, entity_id=entity.id, job_id=job.id,
                                file_uri=storage.write_bytes(f"{job.id}/raw/acme.xlsx", content),
                                original_filename="acme.xlsx", sha256=hashlib.sha256(content).hexdigest(),
                                status="uploaded"))
        db.session.commit()
        llm = get_llm_gateway()
        assert DataSupervisor(app, llm).run_stage(job, job.dataset_version_id), job.progress_message
        assert AnalysisSupervisor(app, llm).run_stage(job, job.dataset_version_id)
        assert DeliverySupervisor(app, llm).run_stage(job, job.dataset_version_id)
        yield job


# ------------------------------------------------------------------ unit-level rules

def test_unit_scale_is_detected_from_the_document_not_the_model():
    assert detect_unit_scale("As at March 31, 2026  |  (₹ crore)") == 1e7
    assert detect_unit_scale("(Rs in lakhs)") == 1e5
    assert detect_unit_scale("INR '000") == 1e3
    assert detect_unit_scale("USD millions") == 1e6
    assert detect_unit_scale("Particulars") is None


def test_repeated_labels_resolve_by_section():
    assert contextual_account("  Borrowings", "EQUITY AND LIABILITIES > Non-current liabilities > Financial liabilities",
                              "BS") == "BS.NCL.LONG_TERM_BORROWINGS"
    assert contextual_account("Borrowings", "Current liabilities > Financial liabilities", "BS") == \
        "BS.CL.SHORT_TERM_BORROWINGS"
    assert contextual_account("Current tax", "Tax expense", "PL") == "PL.TAX"


def test_sheet_roles():
    assert sheet_role("Balance Sheet", None, set()) == "primary"
    assert sheet_role("Loan Schedules", None, {"BS.NCL.LONG_TERM_BORROWINGS"}) == "supporting"
    assert sheet_role("Debtor Ageing", None, set()) == "supporting"
    assert sheet_role("Sheet1", None, {"PL.REVENUE", "PL.PAT", "PL.TAX"}) == "primary"


def test_parser_keeps_sections_and_skips_non_period_subtables(tmp_path):
    sheets = read_excel(str(build_workbook(tmp_path / "a.xlsx")))
    bs = {(r.label, r.section.split(" > ")[-1] if r.section else ""): r for r in sheets["Balance Sheet"]["table"].rows}
    assert ("Borrowings", "Financial liabilities") in bs
    sections = [r.section for r in sheets["Balance Sheet"]["table"].rows if r.label == "Borrowings"]
    assert "Non-current liabilities" in sections[0] and "Current liabilities" in sections[1]
    note_labels = {r.label for r in sheets["Borrowings Note"]["table"].rows}
    assert "Bank A" not in note_labels  # lender / rate / terms columns are not periods
    ageing = {r.label for r in sheets["Receivables Ageing"]["table"].rows}
    assert "Undisputed" not in ageing


def test_exceptional_sign_is_read_from_the_statement():
    loss_shown_negative = {"PL.PBEIT": 1500, "PL.EXCEPTIONAL_ITEMS": -120, "PL.PBT": 1380}
    loss_shown_positive = {"PL.PBEIT": 1500, "PL.EXCEPTIONAL_ITEMS": 120, "PL.PBT": 1380}
    assert exceptional_effect(loss_shown_negative)[0] == -120
    assert exceptional_effect(loss_shown_positive)[0] == -120


def test_flat_pl_without_subtotals_still_reconciles_with_positive_exceptional():
    f = {"PL.REVENUE": 1000, "PL.OTHER_INCOME": 10, "PL.COGS": 500, "PL.PURCHASES_STOCK_IN_TRADE": 50,
         "PL.CHANGES_IN_INVENTORY": -20, "PL.EMPLOYEE_COST": 100, "PL.FINANCE_COST": 30, "PL.DEPRECIATION": 40,
         "PL.OTHER_EXPENSES": 60, "PL.EXCEPTIONAL_ITEMS": 25, "PL.PBT": 225, "PL.TAX": 50, "PL.PAT": 175}
    results = {r["check_code"]: r for r in check_pl_cascade(f)}
    assert results["PL_SUBTOTALS"]["status"] == "pass", results["PL_SUBTOTALS"]


def test_missing_inputs_are_reported_not_silently_passed():
    results = check_pl_cascade({"PL.REVENUE": 1000, "PL.PAT": 100})
    assert [r["status"] for r in results if r["check_code"] == "PL_SUBTOTALS"] == ["skipped"]


# ------------------------------------------------------------------ end-to-end invariants

def test_statements_reconcile_end_to_end(app, acme_job):
    with app.app_context():
        checks = ValidationResult.query.filter_by(dataset_version=acme_job.dataset_version_id).all()
        by_code = {}
        for c in checks:
            by_code.setdefault(c.check_code, []).append(c.status)
        for code in ("BS_BALANCE", "BS_ASSET_SIDE", "BS_FUNDING_SIDE", "PL_OPERATING", "PL_EXCEPTIONAL", "PL_TAX",
                     "PL_SUBTOTALS", "CF_CASH_TIE", "PL_BS_LINK"):
            assert by_code.get(code) and set(by_code[code]) == {"pass"}, (code, by_code.get(code))
        # 'Power and fuel' has no canonical line: a classification warning, never a blocker
        assert set(by_code["PL_EXPENSE_LINES"]) == {"warn"}
        assert "SCHEDULE_TIE" in by_code and "fail" not in by_code["SCHEDULE_TIE"]
        # the job passed the data gate without any analyst override and without guesses
        assert ReviewItem.query.filter_by(job_id=acme_job.id, kind="reconciliation").count() == 0
        assert ReviewItem.query.filter_by(job_id=acme_job.id, kind="mapping").count() <= 1  # only 'Power and fuel'


def test_ledger_values_come_from_the_statements(app, acme_job):
    with app.app_context():
        f = load_facts_by_period(acme_job.dataset_version_id)[FY25]
    assert f["BS.NCL.LONG_TERM_BORROWINGS"] == 1500 * LAKH
    assert f["BS.CL.SHORT_TERM_BORROWINGS"] == 400 * LAKH  # not lost to the repeated 'Borrowings' label
    assert f["BS.CL.TRADE_PAYABLES"] == 1100 * LAKH  # the two split lines, summed
    assert f["PL.TAX"] == 350 * LAKH  # the stated total, not total + components
    assert f["PL.EXCEPTIONAL_ITEMS"] == -120 * LAKH
    assert f["BS.EQ.RESERVES"] == 4600 * LAKH
    # 'other' buckets are derived from the stated subtotals, so each side foots
    assert f["BS.CA.OTHER"] == pytest.approx((2600 - 1200 - 900 - 300) * LAKH)
    assert f["BS.NCA.OTHER"] == pytest.approx((6500 - 5000) * LAKH)
    assert f["BS.CL.OTHER"] == pytest.approx((2000 - 400 - 1100) * LAKH)
    assert f["BS.CA.OTHER"] < f["BS.CA.TOTAL"] and f["BS.NCA.OTHER"] < f["BS.NCA.TOTAL"]


def test_profit_bridge_foots_without_a_plug(app, acme_job):
    with app.app_context():
        bridge = blackboard.read(acme_job.id, "detailed_analysis")["profit_bridge"]
    labels = {s["label"]: s["amount"] for s in bridge["steps"]}
    assert bridge["reconciled"] is True and abs(bridge["unexplained"]) < 1
    assert "Unreconciled difference" not in labels
    assert labels["Exceptional items"] == pytest.approx(-90 * LAKH)  # -120 vs -30: a bigger loss
    assert labels["Other expense captions"] == pytest.approx(-50 * LAKH)  # Power and fuel 500 vs 450
    assert labels["Expenditure capitalised"] == pytest.approx(10 * LAKH)


def test_balance_sheet_chart_matches_the_tables(app, acme_job):
    with app.app_context():
        analysis = blackboard.read(acme_job.id, "detailed_analysis")
        charts = {c["title"]: c for c in blackboard.read(acme_job.id, "charts")}
    table = {r["account_id"]: r["common_size"] for r in analysis["statements"]["BS"]}
    owns = charts["Balance Sheet Structure"]["spec"]["panels"][0]["series"]
    assert owns["Fixed assets (PPE)"][-1] == pytest.approx(table["BS.NCA.PPE"]["2025-03-31"])
    funded = charts["Balance Sheet Structure"]["spec"]["panels"][1]["series"]
    assert funded["Short-term debt"][-1] == pytest.approx(400 / 9100)
    for panel in charts["Balance Sheet Structure"]["spec"]["panels"]:
        for i in range(2):
            assert sum(v[i] for v in panel["series"].values()) == pytest.approx(1.0, abs=0.006)


def test_money_is_shown_in_the_documents_unit_everywhere(app, acme_job):
    """The ledger stores rupees; every rendered amount must read in the filing's unit
    (lakhs here) -- a table printing full rupees next to a chart in lakhs reads as a 10^5 error."""
    import re

    from app.models.report import Report
    from app.utils.money import format_money
    with app.app_context():
        report = Report.query.filter_by(dataset_version=acme_job.dataset_version_id).first()
        html = storage.resolve(report.html_uri).read_text(encoding="utf-8")
        charts = blackboard.read(acme_job.id, "charts")
    assert not re.findall(r"Rs\.? ?-?\d{1,3}(?:,\d{2}){2,},\d{3}\b(?! L)", html), "full-rupee amounts in report"
    assert "Rs 10,000.00 L" in html  # revenue 10,000 lakh, as stated in the filing
    takeaways = " ".join(c["takeaway"] for c in charts)
    assert " L" in takeaways and "Cr" not in takeaways
    assert format_money(-398_400_000_00.0, 1e7) == "-Rs 3,984.00 Cr"


def test_free_cash_flow_is_ocf_minus_capex(app, acme_job):
    from app.models.metric import Metric
    with app.app_context():
        def value(code):
            return float(Metric.query.filter_by(dataset_version=acme_job.dataset_version_id, metric_code=code,
                                                period_end=FY25).one().value)
        assert value("free_cash_flow") == pytest.approx((1700 - 800) * LAKH)  # OCF - purchase of capital assets
        assert value("net_cash_after_investing") == pytest.approx((1700 - 800) * LAKH)
        charts = {c["title"]: c for c in blackboard.read(acme_job.id, "charts")}
    assert "Free cash flow (OCF - capex)" in charts["Cash Flow Profile"]["spec"]["series"]


def test_free_cash_flow_excludes_acquisitions():
    from app.tools.calc.metrics import free_cash_flow, net_cash_after_investing
    f = {"CF.OPERATING": 23505.68, "CF.CAPEX": -11105.71, "CF.INVESTING": -34231.43}  # buys subsidiaries too
    assert free_cash_flow(f) == pytest.approx(12399.97)
    assert net_cash_after_investing(f) == pytest.approx(-10725.75)


def test_long_chart_takeaways_wrap_inside_the_figure(app):
    import matplotlib.pyplot as plt

    from app.tools.chart_render import _header
    fig = plt.figure(figsize=(9.5, 4.8))
    top_short = _header(fig, "Title", "short")
    fig2 = plt.figure(figsize=(9.5, 4.8))
    top_long = _header(fig2, "Title", "x " * 150)
    wrapped = [t for t in fig2.texts if t.get_text().startswith("x")][0].get_text()
    assert wrapped.count("\n") >= 1 and max(len(line) for line in wrapped.split("\n")) <= 9.5 * 14
    assert top_long < top_short  # the plot area moves down to make room
    plt.close("all")


def test_ebitda_includes_every_expense_line(app, acme_job):
    from app.models.metric import Metric
    with app.app_context():
        ebitda = Metric.query.filter_by(dataset_version=acme_job.dataset_version_id, metric_code="ebitda",
                                        period_end=FY25).one()
    # total income - (total expenses - depreciation - finance costs)
    assert float(ebitda.value) == pytest.approx((10200 - (8700 - 400 - 250)) * LAKH)
