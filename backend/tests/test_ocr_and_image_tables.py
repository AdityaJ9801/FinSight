from unittest.mock import MagicMock, patch
import pytest
from PIL import Image, ImageDraw

from app.tools.parsers.ocr import (
    _clean_num,
    _parse_table_from_text_lines,
    extract_tables_from_image,
    is_ocr_available,
    ocr_extract_text,
    ocr_extract_tables,
    preprocess_image,
)
from app.tools.parsers import RawTable, RawRow


def test_clean_num_handles_formats():
    assert _clean_num("1,234.50") == 1234.50
    assert _clean_num("(500.00)") == -500.00
    assert _clean_num("-250") == -250.0
    assert _clean_num("—") == 0.0
    assert _clean_num("nil") == 0.0
    assert _clean_num("invalid") is None


def test_parse_table_from_text_lines():
    sample_text = """
    Demo Manufacturing Limited
    Statement of Profit and Loss
    (Amounts in INR Thousands)

    Line Item 2023-03-31 2024-03-31
    Revenue from Operations 10000000 12000000
    Cost of Materials Consumed 6000000 7000000
    Employee Benefit Expenses 1200000 1500000
    Profit Before Tax 2800000 3500000
    """
    tables = _parse_table_from_text_lines(sample_text, name="test_pnl")
    assert len(tables) == 1
    table = tables[0]
    assert table.periods == ["2023-03-31", "2024-03-31"]
    assert len(table.rows) == 4

    rev_row = next(r for r in table.rows if "Revenue from Operations" in r.label)
    assert rev_row.values["2023-03-31"] == 10000000.0
    assert rev_row.values["2024-03-31"] == 12000000.0


def test_preprocess_image():
    # Create small test image
    img = Image.new("RGB", (300, 100), color="white")
    processed = preprocess_image(img)
    # Check that width was upscaled to at least 1400px for OCR readability
    assert processed.width >= 1400
    assert processed.mode == "L"


def test_extract_tables_from_image_coordinate_mock():
    # Mock pytesseract.image_to_data to verify coordinate clustering and table parsing
    mock_data = {
        "text": [
            "Demo", "Corp", "",
            "Line", "Item", "2023", "2024",
            "Revenue", "1000", "1200",
            "Expenses", "600", "700",
        ],
        "conf": ["90", "90", "-1", "95", "95", "95", "95", "95", "95", "95", "95", "95", "95"],
        "left": [50, 110, 0, 50, 95, 300, 450, 50, 300, 450, 50, 300, 450],
        "top": [20, 20, 0, 60, 60, 60, 60, 100, 100, 100, 140, 140, 140],
        "width": [50, 50, 0, 40, 40, 60, 60, 80, 50, 50, 80, 50, 50],
        "height": [20, 20, 0, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20],
    }

    with patch("app.tools.parsers.ocr.is_ocr_available", return_value=True), \
         patch("pytesseract.image_to_data", return_value=mock_data):
        img = Image.new("RGB", (600, 300), color="white")
        tables = extract_tables_from_image(img, name="test_img")
        assert len(tables) == 1
        t = tables[0]
        assert any("2023" in p for p in t.periods)
        assert any("2024" in p for p in t.periods)
        labels = [r.label for r in t.rows]
        assert any("Revenue" in lbl for lbl in labels)
        assert any("Expenses" in lbl for lbl in labels)


def test_ocr_extract_tables_unsupported_or_empty(tmp_path):
    txt_file = tmp_path / "dummy.txt"
    txt_file.write_text("not an image")
    with patch("app.tools.parsers.ocr.is_ocr_available", return_value=True):
        res = ocr_extract_tables(str(txt_file))
        assert res == []


def test_live_tesseract_ocr_table_extraction(tmp_path):
    if not is_ocr_available():
        pytest.skip("Tesseract binary not installed on this host")

    img_path = tmp_path / "test_table.png"
    img = Image.new("RGB", (900, 350), color="white")
    draw = ImageDraw.Draw(img)

    lines = [
        "Line Item                2023        2024",
        "Revenue from Operations  10000000    12000000",
        "Cost of Materials         6000000     7000000",
        "Net Profit                4000000     5000000",
    ]
    y = 30
    for line in lines:
        draw.text((40, y), line, fill="black")
        y += 50

    img.save(img_path)

    text = ocr_extract_text(str(img_path))
    assert "Revenue" in text or "Profit" in text

    tables = ocr_extract_tables(str(img_path))
    assert len(tables) >= 1
    t = tables[0]
    assert len(t.rows) >= 2
    row_labels = " ".join(r.label for r in t.rows)
    assert "Revenue" in row_labels or "Cost" in row_labels or "Profit" in row_labels
