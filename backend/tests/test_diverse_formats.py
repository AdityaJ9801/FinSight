import os
import pytest
from app.tools.parsers.csv_tool import read_csv, read_csv_tables
from app.tools.parsers.excel import read_excel
from app.domain.dataset_analyzer import analyze_dataset_profile
from app.domain.dynamic_chart_builder import generate_chart_for_prompt
from app.orchestrator import blackboard


def test_diverse_sample_data_extraction():
    data_dir = r"D:\PROJECT\Agentic Financial Analysis\sample_data"
    
    # 1. Financials.csv
    p_fin = os.path.join(data_dir, "Financials.csv")
    tables_fin = read_csv_tables(p_fin)
    assert len(tables_fin) >= 2
    summary_tbl = tables_fin[0]
    records_tbl = tables_fin[1]
    assert summary_tbl.dataset is not None
    assert "Segment" in summary_tbl.dataset["dimensions"]
    assert "Sales" in summary_tbl.dataset["measures"]
    assert "Government" in summary_tbl.dataset["aggregations"]["Segment"]

    # 2. Profit and loss.csv
    p_pnl = os.path.join(data_dir, "Profit and loss.csv")
    tables_pnl = read_csv_tables(p_pnl)
    assert len(tables_pnl) >= 1
    assert len(tables_pnl[0].periods) >= 3

    # 3. Tata Steel Financials.xlsx
    p_tata = os.path.join(data_dir, "Tata Steel Financials.xlsx")
    sheets_tata = read_excel(p_tata)
    assert "Balance Sheet" in sheets_tata
    assert "P&L Statement" in sheets_tata
    assert sheets_tata["Balance Sheet"]["table"] is not None
    assert len(sheets_tata["Balance Sheet"]["table"].rows) > 10

    # 4. sales regi.xlsx
    p_sales = os.path.join(data_dir, "sales regi.xlsx")
    sheets_sales = read_excel(p_sales)
    assert "Sales Register_summary" in sheets_sales
    sr_tbl = sheets_sales["Sales Register_summary"]["table"]
    assert sr_tbl.dataset is not None
    assert "Debit Amount" in sr_tbl.dataset["measures"]
    assert "Particulars" in sr_tbl.dataset["dimensions"]


def test_dataset_first_analysis_and_dynamic_charts(app):
    with app.app_context():
        job_id = "test_job_diverse_123"
        data_dir = r"D:\PROJECT\Agentic Financial Analysis\sample_data"
        tables_fin = read_csv_tables(os.path.join(data_dir, "Financials.csv"))
        
        # Write structured dataset to blackboard
        blackboard.write(job_id, "structured_datasets", [tables_fin[0].dataset])

        # 1. Dataset-first analysis
        profile = analyze_dataset_profile(job_id)
        assert profile["datasets_count"] == 1
        assert len(profile["findings"]) >= 1
        assert len(profile["dynamic_chart_candidates"]) >= 1

        # 2. On-demand dynamic chart generation for chat query
        chart = generate_chart_for_prompt(job_id, "Please plot sales by segment")
        assert chart is not None
        assert "Segment" in chart["title"]
        assert chart["png_base64"].startswith("data:image/png;base64,")

        # 3. Blackboard charts updated
        all_charts = blackboard.read(job_id, "charts") or []
        assert any(c["chart_id"] == chart["chart_id"] for c in all_charts)
