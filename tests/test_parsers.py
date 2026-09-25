"""Covers the two extraction gaps the fake-LLM e2e test can't exercise on its own (the
seed CSVs have no metadata preamble and are single-sheet): a real file whose table doesn't
start at row 0, and a workbook with multiple sheets that each need their own detection.
"""
import openpyxl
import pytest

from app.tools.parsers import csv_tool, excel


@pytest.fixture()
def tmp_csv_with_preamble(tmp_path):
    path = tmp_path / "statement.csv"
    path.write_text(
        "Demo Widgets Pvt Ltd\n"
        "Profit and Loss Statement\n"
        "(All amounts in INR)\n"
        "\n"
        "Line Item,2023-03-31,2024-03-31\n"
        "Revenue from Operations,10000000,12000000\n"
        "Cost of Materials Consumed,6000000,7000000\n",
        encoding="utf-8",
    )
    return str(path)


def test_csv_read_skips_metadata_preamble(tmp_csv_with_preamble):
    table = csv_tool.read_csv(tmp_csv_with_preamble)
    assert table.periods == ["2023-03-31", "2024-03-31"]
    labels = {r.label for r in table.rows}
    assert labels == {"Revenue from Operations", "Cost of Materials Consumed"}
    revenue_row = next(r for r in table.rows if r.label == "Revenue from Operations")
    assert revenue_row.values["2024-03-31"] == 12000000.0


def test_csv_read_grid_returns_raw_rows_for_detection(tmp_csv_with_preamble):
    grid = csv_tool.read_csv_grid(tmp_csv_with_preamble)
    assert grid[0][0] == "Demo Widgets Pvt Ltd"
    assert grid[4][0] == "Line Item"


@pytest.fixture()
def tmp_multi_sheet_workbook(tmp_path):
    path = tmp_path / "statements.xlsx"
    wb = openpyxl.Workbook()

    ws_bs = wb.active
    ws_bs.title = "Balance Sheet"
    ws_bs.append(["Demo Widgets Pvt Ltd"])
    ws_bs.append(["Balance Sheet as at 31 March 2024"])
    ws_bs.append([])
    ws_bs.append(["Line Item", "2023-03-31", "2024-03-31"])
    ws_bs.append(["Cash and Cash Equivalents", 1200000, 1500000])
    ws_bs.append(["Trade Receivables", 1500000, 1800000])

    ws_pl = wb.create_sheet("P&L")
    ws_pl.append(["Line Item", "2023-03-31", "2024-03-31"])
    ws_pl.append(["Revenue from Operations", 10000000, 12000000])

    wb.save(path)
    return str(path)


def test_excel_read_processes_every_sheet_with_its_own_header_offset(tmp_multi_sheet_workbook):
    sheets = excel.read_excel(tmp_multi_sheet_workbook)

    assert set(sheets.keys()) == {"Balance Sheet", "P&L"}

    bs_info = sheets["Balance Sheet"]
    assert bs_info["header_row_idx"] == 3
    assert bs_info["confident"] is True
    bs_labels = {r.label for r in bs_info["table"].rows}
    assert bs_labels == {"Cash and Cash Equivalents", "Trade Receivables"}

    pl_info = sheets["P&L"]
    assert pl_info["header_row_idx"] == 0
    pl_labels = {r.label for r in pl_info["table"].rows}
    assert pl_labels == {"Revenue from Operations"}


def test_excel_read_grid_previews_every_sheet(tmp_multi_sheet_workbook):
    grids = excel.read_excel_grid(tmp_multi_sheet_workbook)
    assert set(grids.keys()) == {"Balance Sheet", "P&L"}
    assert grids["Balance Sheet"][0][0] == "Demo Widgets Pvt Ltd"
