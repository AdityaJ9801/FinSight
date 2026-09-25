from app.tools.table_detect import detect_header_row_heuristic


def test_detects_header_row_with_metadata_preamble():
    grid = [
        ["Demo Widgets Pvt Ltd"],
        ["Balance Sheet as at 31 March 2024"],
        ["(All amounts in INR unless otherwise stated)"],
        [],
        ["Line Item", "2023-03-31", "2024-03-31"],
        ["Cash and Cash Equivalents", "1200000", "1500000"],
        ["Trade Receivables", "1500000", "1800000"],
    ]
    assert detect_header_row_heuristic(grid) == 4


def test_row_zero_is_still_detected_when_it_is_the_real_header():
    grid = [
        ["Line Item", "2023-03-31", "2024-03-31"],
        ["Cash and Cash Equivalents", "1200000", "1500000"],
    ]
    assert detect_header_row_heuristic(grid) == 0


def test_returns_none_when_nothing_looks_like_a_table():
    grid = [["Just some notes"], ["More prose, no numbers here"], ["Still nothing tabular"]]
    assert detect_header_row_heuristic(grid) is None


def test_trailing_footnote_after_data_does_not_confuse_detection():
    grid = [
        ["Line Item", "2024-03-31"],
        ["Revenue from Operations", "12000000"],
        ["Note: figures are provisional", ""],
    ]
    assert detect_header_row_heuristic(grid) == 0
