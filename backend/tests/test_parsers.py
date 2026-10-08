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


def test_sample1_income_statement_wide_matrix(tmp_path):
    csv_content = (
        'Ebita, JAN - DEC 2019,JAN - DEC 2020,JAN - DEC 2021,JAN - DEC 2022\n'
        ' Income  4300 Sales,"1,500,000.00","1,875,000.00","2,437,500.00","3,656,250.00"\n'
        ' Total Income,"1,500,000.00","1,875,000.00","2,437,500.00","3,656,250.00"\n'
        ' Total Cost of Goods Sold," \t425,850.00","1,217,685.00","2,087,867.30","2,766,207.75"\n'
        ' GROSS PROFIT,"1,074,150.00","657,315.00","349,632.70","890,042.25"\n'
        ' Total Expenses,"138,875.00","58,040.00","109,625.00","351,770.00"\n'
        ' NET OPERATING INCOME,"935,275.00","599,275.00","240,007.70","538,272.25"\n'
        ' NET OTHER INCOME,"-12,500.00","-16,000.00","-40,000.00","-50,000.00"\n'
        ',,,,\n'
        ' NET INCOME,"922,775.00","599,275.00","200,007.70","488,272.25"\n'
    )
    p = tmp_path / "sample1.csv"
    p.write_text(csv_content, encoding="utf-8")

    from app.agents.data.mapper import _parse_period
    from datetime import date

    tables = csv_tool.read_csv_tables(str(p))
    assert len(tables) == 1
    t = tables[0]
    assert t.periods == ["JAN - DEC 2019", "JAN - DEC 2020", "JAN - DEC 2021", "JAN - DEC 2022"]
    assert _parse_period("JAN - DEC 2019") == date(2019, 12, 31)
    assert _parse_period("JAN - DEC 2022") == date(2022, 12, 31)

    labels = [r.label for r in t.rows]
    assert "Income  4300 Sales" in labels
    assert "NET INCOME" in labels
    net_inc = next(r for r in t.rows if r.label == "NET INCOME")
    assert net_inc.values["JAN - DEC 2019"] == 922775.0
    assert net_inc.values["JAN - DEC 2022"] == 488272.25

    cogs = next(r for r in t.rows if r.label == "Total Cost of Goods Sold")
    assert cogs.values["JAN - DEC 2019"] == 425850.0  # verifies embedded tab stripped


def test_sample2_columnar_dataset_financial_sample(tmp_path):
    csv_content = (
        'Segment,Country, Product , Discount Band , Units Sold , Manufacturing Price , Sale Price , Gross Sales , Discounts ,  Sales , COGS , Profit ,Date,Month Number, Month Name ,Year\n'
        'Government,Canada, Carretera , None ," $1,618.50 ", $3.00 , $20.00 ," $32,370.00 ", $-   ," $32,370.00 "," $16,185.00 "," $16,185.00 ",01/01/2014,1, January ,2014\n'
        'Government,Germany, Carretera , None ," $1,513.00 ", $3.00 , $350.00 ," $5,29,550.00 ", $-   ," $5,29,550.00 "," $3,93,380.00 "," $1,36,170.00 ",01/12/2014,12, December ,2014\n'
        'Enterprise,United States of America, Montana , Medium ," $3,627.00 ", $5.00 , $125.00 ," $4,53,375.00 "," $22,668.75 "," $4,30,706.25 "," $4,35,240.00 "," $(4,533.75)",01/07/2014,7, July ,2014\n'
        'Midmarket,France, Paseo , Low , $549.00 , $10.00 , $15.00 ," $8,235.00 ", $-   ," $8,235.00 "," $5,490.00 "," $2,745.00 ",01/09/2013,9, September ,2013\n'
    )
    p = tmp_path / "sample2.csv"
    p.write_text(csv_content, encoding="utf-8")

    tables = csv_tool.read_csv_tables(str(p))
    assert len(tables) == 2
    summary, records = tables[0], tables[1]
    assert summary.name == "csv_summary"
    assert records.name == "csv_records"
    assert summary.periods == ["2013-12-31", "2014-12-31"]

    # Verify accounting negative parentheses parse to float negative
    profit_row = next(r for r in summary.rows if r.label == "Profit")
    assert profit_row.values["2013-12-31"] == 2745.0
    # 2014 profit = 16185.0 + 136170.0 - 4533.75 = 147821.25
    assert profit_row.values["2014-12-31"] == 147821.25

    # Verify Indian lakh comma formatting " $5,29,550.00 " parses correctly
    gross_sales_row = next(r for r in summary.rows if r.label == "Gross Sales")
    # 32370.0 + 529550.0 + 453375.0 = 1015295.0
    assert gross_sales_row.values["2014-12-31"] == 1015295.0

    # Verify records table captures detailed row count
    assert len(records.rows) == 4

