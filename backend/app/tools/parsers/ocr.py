"""OCR and table extraction for images and scanned PDFs.

Uses Tesseract OCR (free, open source) along with image pre-processing,
bounding-box coordinate analysis, and line-level heuristic parsing to
accurately extract both full text and structured financial tables.
"""
from __future__ import annotations

import io
import os
import re
import shutil
from pathlib import Path
from typing import Any

from app.tools.parsers import RawRow, RawTable
from app.tools.registry import tool
from app.tools.table_detect import _looks_numeric, detect_header_row_heuristic


class OcrNotAvailableError(Exception):
    pass


def is_ocr_available() -> bool:
    """Checks whether Tesseract OCR and PIL dependencies are available."""
    try:
        import pytesseract
        from PIL import Image  # noqa: F401

        if shutil.which("tesseract"):
            return True
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def preprocess_image(img: Any) -> Any:
    """Enhance image quality for OCR: grayscale, resize if low-res, contrast boost, sharpen."""
    from PIL import Image, ImageEnhance, ImageFilter

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    gray = img.convert("L")

    # Resize if width < 1400px so small text is readable by OCR
    w, h = gray.size
    if w < 1400:
        scale = 1400.0 / max(w, 1)
        gray = gray.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    # Boost contrast and sharpen edges
    enhancer = ImageEnhance.Contrast(gray)
    contrasted = enhancer.enhance(1.6)
    sharpened = contrasted.filter(ImageFilter.SHARPEN)
    return sharpened


def ocr_image_text(image_input: str | Path | Any) -> str:
    """Extracts raw text from an image using Tesseract."""
    if not is_ocr_available():
        raise OcrNotAvailableError("Tesseract OCR is not installed or available on PATH.")
    import pytesseract
    from PIL import Image

    if isinstance(image_input, (str, Path)):
        with Image.open(str(image_input)) as img:
            processed = preprocess_image(img)
            text = pytesseract.image_to_string(processed, config="--psm 6")
            if len(text.strip()) < 10:
                text = pytesseract.image_to_string(processed, config="--psm 3")
            return text
    else:
        processed = preprocess_image(image_input)
        text = pytesseract.image_to_string(processed, config="--psm 6")
        if len(text.strip()) < 10:
            text = pytesseract.image_to_string(processed, config="--psm 3")
        return text


def ocr_pdf_text(file_path: str, max_pages: int = 5) -> str:
    """Rasterizes and OCRs pages of a scanned PDF."""
    if not is_ocr_available():
        raise OcrNotAvailableError("Tesseract OCR is not installed or available on PATH.")
    try:
        import fitz  # PyMuPDF
        from PIL import Image
    except ImportError as exc:
        raise OcrNotAvailableError(f"Missing PDF/image dependencies: {exc}") from exc

    text_parts: list[str] = []
    doc = fitz.open(file_path)
    try:
        for idx, page in enumerate(doc):
            if idx >= max_pages:
                break
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text_parts.append(ocr_image_text(img))
    finally:
        doc.close()
    return "\n\n".join(text_parts)


def ocr_extract_text(file_path: str, max_pages: int = 5) -> str:
    """Unified text extractor for both images and scanned PDFs."""
    path = Path(file_path)
    ext = path.suffix.lower().lstrip(".")
    if ext == "pdf":
        return ocr_pdf_text(file_path, max_pages=max_pages)
    return ocr_image_text(file_path)


def _clean_num(val_str: str) -> float | None:
    s = str(val_str).strip()
    if s.startswith("(") and s.endswith(")") and len(s) > 2:
        s = "-" + s[1:-1]
    if s in ("-", "—", "–", "nil", "NIL", "Nil", ""):
        return 0.0
    # Clean whitespace after comma/dot in numbers (e.g. '1,19, 24,591.11' -> '1,19,24,591.11')
    s = re.sub(r"(?<=[,\.])\s+", "", s)
    # Fix OCR artifacts like ',.' or '.,'
    s = re.sub(r"[,.]{2,}", ".", s)
    # If ends in comma followed by 2 digits and no dot exists, comma is decimal separator (e.g. '21,07,361,08')
    if "." not in s and re.search(r",(\d{2})$", s):
        s = re.sub(r",(\d{2})$", r".\1", s)
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def detect_statement_periods(text: str, num_cols: int = 2) -> list[str]:
    """Detects period end dates (e.g. '2016-03-31', '2015-03-31') from document text and headers."""
    months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

    m_title = re.search(
        r"(?:as\s+at|year\s+ended|ended|period\s+ended)\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9}),?\s+(\d{4})",
        text[:2500], re.IGNORECASE
    )
    day, mon_str, base_year = 31, "mar", 2026
    if m_title:
        day = int(m_title.group(1))
        mon_str = m_title.group(2).lower()[:3]
        base_year = int(m_title.group(3))
    mon = months.get(mon_str, 3)

    years: list[int] = []
    for line in text.splitlines()[:20]:
        if any(w in line.lower() for w in ("estate", "vadodara", "pincode", "road", "street", "kolkata", "partner")):
            continue
        for y_str in re.findall(r"\b(20\d{2}|19\d{2})\b", line):
            iy = int(y_str)
            if iy not in years:
                years.append(iy)

    if not years:
        years = [base_year, base_year - 1]
    elif len(years) == 1:
        years.append(years[0] - 1)

    dates = [f"{y:04d}-{mon:02d}-{day:02d}" for y in years[:num_cols]]
    return dates


def _parse_table_from_text_lines(text: str, name: str = "table") -> list[RawTable]:
    """Fallback line-by-line parser for clean columnar text output."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return []

    # Look for candidate rows that have text followed by multiple numbers
    parsed_rows: list[tuple[str, list[float]]] = []
    num_re = re.compile(r"^\(?[-–—]?\d[\d,]*(?:\.\d+)?\)?$")

    for line in lines:
        tokens = line.split()
        if len(tokens) < 2:
            continue

        num_vals: list[float] = []
        i = len(tokens) - 1
        while i >= 0:
            tok = tokens[i]
            # Handle split numbers like '1,19,' '24,591.11'
            if i > 0 and (tok.endswith(".11") or tok.endswith(".00") or re.search(r"\.\d{2}$", tok)) and tokens[i - 1].endswith(","):
                combined = tokens[i - 1] + tok
                v = _clean_num(combined)
                if v is not None:
                    num_vals.insert(0, v)
                    i -= 2
                    continue
            if num_re.match(tok) or tok in ("-", "—", "nil"):
                v = _clean_num(tok)
                if v is not None:
                    num_vals.insert(0, v)
            else:
                break
            i -= 1

        label = " ".join(tokens[:i + 1]).strip()
        # Clean label: strip leading numbers, bullets
        clean_lbl = re.sub(r"^(?:\d+[.)]?|[•\*\-_.:]+)\s+", "", label).strip()
        if clean_lbl.lower() in ("no", "no.", "note", "note no", "note no.", "particulars", "amount(rs.)", "amount (rs.)"):
            continue

        if num_vals and clean_lbl:
            parsed_rows.append((clean_lbl, num_vals))

    if not parsed_rows:
        return []

    val_counts = [len(v) for _, v in parsed_rows]
    most_common_cols = max(set(val_counts), key=val_counts.count)

    # Detect Note column: Indian Schedule III has [Particulars, Note No., Period 1, Period 2]
    if most_common_cols >= 3:
        first_vals = [v[0] for _, v in parsed_rows if len(v) == most_common_cols]
        int_count = sum(1 for x in first_vals if x.is_integer() and 1 <= x <= 99)
        if int_count >= len(first_vals) * 0.4:
            new_rows = []
            for lbl, vals in parsed_rows:
                if len(vals) == most_common_cols:
                    new_rows.append((lbl, vals[1:]))
                elif len(vals) == most_common_cols - 1:
                    new_rows.append((lbl, vals))
            parsed_rows = new_rows
            most_common_cols -= 1

    if most_common_cols < 1:
        return []

    periods = detect_statement_periods(text, most_common_cols)

    raw_rows: list[RawRow] = []
    r_idx = 1
    for label, vals in parsed_rows:
        if len(vals) != most_common_cols:
            continue
        values = {periods[j]: vals[j] for j in range(most_common_cols)}
        raw_rows.append(RawRow(
            row_idx=r_idx,
            label=label,
            values=values,
            source_ref={"image": name, "row": r_idx},
        ))
        r_idx += 1

    if not raw_rows:
        return []
    return [RawTable(rows=raw_rows, periods=periods, name=name)]


def extract_tables_from_image(
    image_input: str | Path | Any,
    name: str = "table",
    text: str | None = None,
) -> list[RawTable]:
    """Extracts structured financial tables from an image using word coordinates."""
    if not is_ocr_available():
        raise OcrNotAvailableError("Tesseract OCR is not installed or available on PATH.")
    import pytesseract
    from PIL import Image

    if isinstance(image_input, (str, Path)):
        img = Image.open(str(image_input))
    else:
        img = image_input

    processed = preprocess_image(img)
    w_img, h_img = processed.size
    
    words: list[dict] = []
    
    # Attempt DocTR first (much better bounding boxes for scanned tables)
    try:
        import numpy as np
        from doctr.models import ocr_predictor
        # Initialize a lightweight model (cached internally by doctr)
        model = ocr_predictor(det_arch='db_resnet50', reco_arch='crnn_vgg16_bn', pretrained=True)
        img_np = np.array(processed)
        result = model([img_np])
        
        if result.pages:
            for block in result.pages[0].blocks:
                for line in block.lines:
                    for word in line.words:
                        if word.confidence < 0.15:
                            continue
                        (xmin, ymin), (xmax, ymax) = word.geometry
                        top, bottom = ymin * h_img, ymax * h_img
                        left, right = xmin * w_img, xmax * w_img
                        txt = word.value.strip()
                        if not txt:
                            continue
                        words.append({
                            "text": txt,
                            "left": left,
                            "top": top,
                            "width": right - left,
                            "height": bottom - top,
                            "right": right,
                            "bottom": bottom,
                            "y_center": (top + bottom) / 2.0,
                            "x_center": (left + right) / 2.0,
                        })
    except ImportError:
        pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("DocTR failed (%s), falling back to Tesseract", e)
        
    # Fallback to Tesseract if DocTR wasn't available or returned nothing
    if not words:
        try:
            data = pytesseract.image_to_data(processed, output_type=pytesseract.Output.DICT, config="--psm 6")
        except Exception:
            data = pytesseract.image_to_data(processed, output_type=pytesseract.Output.DICT)

        n_boxes = len(data.get("text", []))
        for i in range(n_boxes):
            txt = (data["text"][i] or "").strip()
            conf = int(data["conf"][i]) if "conf" in data and data["conf"][i] != "-1" else 50
            if not txt or conf < 15:
                continue
            w = data["width"][i]
            h = data["height"][i]
            top = data["top"][i]
            left = data["left"][i]
            words.append({
                "text": txt,
                "left": left,
                "top": top,
                "width": w,
                "height": h,
                "right": left + w,
                "bottom": top + h,
                "y_center": top + h / 2.0,
                "x_center": left + w / 2.0,
            })

    if not words:
        full_text = text or pytesseract.image_to_string(processed)
        return _parse_table_from_text_lines(full_text, name=name)

    # 1. Cluster words into rows based on y_center
    heights = sorted(w["height"] for w in words)
    median_h = heights[len(heights) // 2] if heights else 15
    y_threshold = max(8.0, median_h * 0.65)

    sorted_by_y = sorted(words, key=lambda w: w["y_center"])
    rows: list[list[dict]] = []
    for w in sorted_by_y:
        if not rows:
            rows.append([w])
            continue
        row_y = sum(x["y_center"] for x in rows[-1]) / len(rows[-1])
        if abs(w["y_center"] - row_y) <= y_threshold:
            rows[-1].append(w)
        else:
            rows.append([w])

    for r in rows:
        r.sort(key=lambda w: w["left"])

    if text:
        line_tables = _parse_table_from_text_lines(text, name=name)
    else:
        full_text = "\n".join(" ".join(w["text"] for w in r) for r in rows)
        line_tables = _parse_table_from_text_lines(full_text, name=name)
        if not line_tables:
            raw_text = ocr_image_text(processed)
            line_tables = _parse_table_from_text_lines(raw_text, name=name)

    # 2. Identify numeric columns
    numeric_words = [w for w in words if _looks_numeric(w["text"])]
    period_year_re = re.compile(r"^(?:FY)?(?:19|20)\d\d$|^(?:31[-/.]03[-/.](?:19|20)?\d\d)$", re.IGNORECASE)
    period_words = [w for w in words if period_year_re.match(w["text"].replace(" ", ""))]

    col_anchors: list[float] = []
    if numeric_words:
        num_x = sorted(w["x_center"] for w in numeric_words)
        x_clusters: list[list[float]] = []
        for x in num_x:
            if not x_clusters:
                x_clusters.append([x])
            elif x - (sum(x_clusters[-1]) / len(x_clusters[-1])) < median_h * 3.5:
                x_clusters[-1].append(x)
            else:
                x_clusters.append([x])
        col_anchors = [sum(c) / len(c) for c in x_clusters if len(c) >= 2]

    if not col_anchors and period_words:
        col_anchors = sorted(w["x_center"] for w in period_words)

    # Fallback to line parser if column layout couldn't be detected
    if not col_anchors:
        return line_tables

    col_anchors.sort()
    first_col_x = col_anchors[0]
    label_max_x = first_col_x - (median_h * 1.5)

    # 3. Map row words into 2D grid: [label, col_1, col_2, ...]
    grid: list[list[str]] = []
    for r in rows:
        label_parts = []
        col_buckets: list[list[str]] = [[] for _ in col_anchors]
        for w in r:
            if w["right"] <= label_max_x or (w["x_center"] < first_col_x - median_h * 1.5 and not _looks_numeric(w["text"])):
                label_parts.append(w["text"])
            else:
                best_col = min(range(len(col_anchors)), key=lambda idx: abs(w["x_center"] - col_anchors[idx]))
                col_buckets[best_col].append(w["text"])

        row_label = " ".join(label_parts).strip()
        row_cols = [" ".join(bucket).strip() for bucket in col_buckets]
        grid.append([row_label] + row_cols)

    # 4. Detect header row
    header_idx = detect_header_row_heuristic(grid)
    if header_idx is None:
        for idx in range(min(5, len(grid))):
            cand = grid[idx][1:]
            if any(c for c in cand) and not all(_looks_numeric(c) for c in cand if c):
                header_idx = idx
                break
        if header_idx is None:
            header_idx = 0

    header = grid[header_idx]
    periods = []
    for j, c in enumerate(header[1:], start=1):
        clean_p = c.strip() or f"Period_{j}"
        periods.append(clean_p)

    raw_rows: list[RawRow] = []
    for r_idx, row in enumerate(grid[header_idx + 1:], start=1):
        label = row[0].strip()
        if not label:
            continue
        values: dict[str, float] = {}
        for j, period in enumerate(periods):
            if j + 1 >= len(row) or not row[j + 1]:
                continue
            val = _clean_num(row[j + 1])
            if val is not None:
                values[period] = val
        if values:
            raw_rows.append(RawRow(
                row_idx=r_idx,
                label=label,
                values=values,
                source_ref={"image": name, "row": r_idx},
            ))

    line_row_count = len(line_tables[0].rows) if line_tables else 0
    # If coordinate extraction found few rows, or line parser found at least as many rows, use line parser!
    if len(raw_rows) < 4 or line_row_count >= len(raw_rows):
        if line_tables:
            return line_tables

    if not raw_rows:
        return line_tables

    return [RawTable(rows=raw_rows, periods=periods, name=name)]


def ocr_extract_tables(file_path: str) -> list[RawTable]:
    """Unified table extractor for image files (.png, .jpg, .tiff, etc.) and scanned PDFs."""
    if not is_ocr_available():
        raise OcrNotAvailableError(
            "Tesseract OCR is not installed or enabled. "
            "Please ensure tesseract-ocr is installed."
        )
    path = Path(file_path)
    ext = path.suffix.lower().lstrip(".")
    tables: list[RawTable] = []

    if ext == "pdf":
        import fitz
        from PIL import Image

        doc = fitz.open(file_path)
        try:
            for page_num, page in enumerate(doc, start=1):
                pix = page.get_pixmap(dpi=200)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                page_text = ocr_image_text(img)
                lower_text = page_text.lower()

                # Infer financial statement type from page text header lines
                table_suffix = ""
                page_lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()][:8]
                for l in page_lines:
                    if re.search(r"^balance\s+sheet(?:\s+as\s+(?:at|of))?\b", l, re.IGNORECASE) and not any(w in l.lower() for w in ("forming part", "annexed to")):
                        table_suffix = "_balance_sheet"
                        break
                    if re.search(r"^(?:statement\s+of\s+)?profit\s+(?:and|&)\s+loss\b", l, re.IGNORECASE):
                        table_suffix = "_pnl"
                        break
                    if re.search(r"^(?:statement\s+of\s+)?cash\s+flows?\b", l, re.IGNORECASE):
                        table_suffix = "_cash_flow"
                        break

                table_name = f"page{page_num}{table_suffix}"
                t = extract_tables_from_image(img, name=table_name, text=page_text)
                tables.extend(t)
        finally:
            doc.close()
    elif ext in ("png", "jpg", "jpeg", "webp", "tiff", "tif", "bmp"):
        from PIL import Image, ImageSequence

        with Image.open(file_path) as img:
            frames = list(ImageSequence.Iterator(img))
            for idx, frame in enumerate(frames, start=1):
                frame_img = frame.copy()
                page_text = ocr_image_text(frame_img)
                lower_text = (page_text + " " + path.stem).lower()
                suffix = ""
                if "balance sheet" in lower_text or "balance_sheet" in lower_text:
                    suffix = "_balance_sheet"
                elif any(k in lower_text for k in ("profit and loss", "profit & loss", "statement of profit", "income statement", "pnl")):
                    suffix = "_pnl"
                elif "cash flow" in lower_text or "cash_flow" in lower_text:
                    suffix = "_cash_flow"

                frame_name = f"{path.stem}_frame{idx}{suffix}" if len(frames) > 1 else f"{path.stem}{suffix}"
                t = extract_tables_from_image(frame_img, name=frame_name, text=page_text)
                tables.extend(t)
    return tables


def ocr_pdf(file_path: str, enabled: bool = True) -> str:
    """Legacy helper for backward compatibility."""
    return ocr_extract_text(file_path)


tool("ocr.extract_text", allowed_agents=["intake_classifier", "extractor"])(ocr_extract_text)
tool("ocr.extract_tables", allowed_agents=["extractor"])(ocr_extract_tables)
tool("ocr.page", allowed_agents=["extractor"])(ocr_pdf)
