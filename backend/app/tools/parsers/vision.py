"""Vision-based table extraction for scanned PDFs using gpt-4o-mini.

Converts each page to a base64-encoded PNG and asks the configured vision-capable
LLM to extract the financial table (periods + rows) as structured JSON.
This is the primary extraction path when:
  - The LLM backend is OpenAI (gpt-4o-mini / gpt-4o) -- confirmed vision-capable
  - The file is a scanned PDF (no selectable text)

The custom Qwen3-14B endpoint (llm.smigan.com) does NOT support image inputs
(returns HTTP 422 on multimodal messages), so this module falls back to Tesseract
when the active backend is not OpenAI.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

from app.tools.parsers import RawRow, RawTable

log = logging.getLogger(__name__)

MAX_VISION_PAGES = 20
_MAX_WIDTH_PX = 1600


def _is_vision_backend() -> bool:
    """Returns True when the active backend supports vision (OpenAI or Custom API)."""
    try:
        from flask import current_app
        backend = current_app.config.get("LLM_BACKEND", "")
        # 'real' is the custom endpoint
        return backend in ("openai", "openai_reasoning", "auto", "reasoning", "auto_reasoning", "real")
    except Exception:
        return False


def _llm_cfg() -> tuple[str, str, str]:
    """Returns (base_url, api_key, model_name) for vision calls."""
    try:
        from flask import current_app
        cfg = current_app.config
        backend = cfg.get("LLM_BACKEND", "")
        
        if backend == "real":
            base_url = cfg.get("LLM_BASE_URL", "").rstrip("/")
            api_key = cfg.get("LLM_API_KEY", "")
            model = cfg.get("LLM_MODEL_NAME", "default")
            return base_url, api_key, model
            
        base_url = cfg.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        api_key = cfg.get("OPENAI_API_KEY", "")
        model = cfg.get("OPENAI_MODEL_NAME", "gpt-4o-mini")
        return base_url, api_key, model
    except Exception:
        return "https://api.openai.com/v1", "", "gpt-4o-mini"


def _page_to_base64(img: Any) -> str:
    """Converts a PIL Image to a base64-encoded PNG, resizing if wider than _MAX_WIDTH_PX."""
    from PIL import Image
    if not isinstance(img, Image.Image):
        raise TypeError(f"Expected PIL Image, got {type(img)}")
    w, h = img.size
    if w > _MAX_WIDTH_PX:
        scale = _MAX_WIDTH_PX / w
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


_VISION_SYSTEM = """\
You are an expert financial statement extractor for Indian company documents.
You receive a page image from a scanned Balance Sheet, P&L, or Cash Flow Statement.

Your task:
1. Find every financial data table on the page.
2. Extract column headers = accounting period dates.
   Convert any date format to ISO: "31.03.2016" -> "2016-03-31", "2015-16" -> "2016-03-31".
3. Extract every row: its exact line-item label (leftmost column text) and numeric values per period.
   - Indian numbers: read exactly as printed (commas are thousand-separators).
   - A "Note No." or schedule reference column (small integer 1-50 between label and amounts) must be SKIPPED.
   - Negative values in brackets like (12,345) -> -12345.
   - Blank / nil / dash cells -> 0.
4. For Balance Sheet rows, output which section they belong to:
   "equity", "non_current_liabilities", "current_liabilities", "non_current_assets", "current_assets".
   Leave section blank for P&L rows.
5. Skip non-data rows: company name, auditor signature, address, page numbers.

Return ONLY a JSON object in this exact shape:
{
  "pages": [
    {
      "statement_type": "balance_sheet",
      "periods": ["2016-03-31"],
      "rows": [
        {"label": "Share Capital", "section": "equity", "values": {"2016-03-31": 500000.0}},
        {"label": "Revenue from Operations", "section": "", "values": {"2016-03-31": 45000000.0}}
      ]
    }
  ]
}
If the page has no financial data, return {"pages": [{"periods": [], "rows": []}]}.
"""


def _call_vision_api(img_b64: str, page_num: int) -> dict:
    """Calls the vision endpoint and returns parsed JSON."""
    import requests as _req
    base_url, api_key, model = _llm_cfg()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text",
                 "text": f"Page {page_num} of a scanned Indian financial statement. Extract all financial table data as JSON."},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ]},
        ],
        "max_tokens": 4096,
        "temperature": 0.0,
    }
    resp = _req.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=(10, 120),
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    # Strip markdown fences the model might add despite instructions
    content = re.sub(r"^```[a-z]*\n?", "", content.strip())
    content = re.sub(r"\n?```$", "", content.strip())
    return json.loads(content)


def _normalise_period(s: str) -> str | None:
    """Converts various date formats to ISO YYYY-MM-DD."""
    if not s:
        return None
    s = s.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    # DD.MM.YYYY or DD/MM/YYYY
    m = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    # YYYY
    m = re.match(r"^(\d{4})$", s)
    if m:
        return f"{m.group(1)}-03-31"
    # FY 2015-16 style
    m = re.match(r"(?:FY\s*)?(\d{2,4})[-/](\d{2,4})", s, re.IGNORECASE)
    if m:
        y2 = int(m.group(2))
        if y2 < 100:
            y1_str = m.group(1)
            century = str(int(y1_str))[:2] if len(y1_str) == 4 else "20"
            y2 = int(f"{century}{y2:02d}")
        return f"{y2}-03-31"
    return None


def _stmt_suffix(stmt_type: str) -> str:
    return {"balance_sheet": "_balance_sheet", "pnl": "_pnl", "cash_flow": "_cash_flow"}.get(stmt_type, "")


def vision_extract_tables_from_pdf(file_path: str) -> list[RawTable]:
    """
    Primary extraction path for scanned PDFs via gpt-4o-mini vision.

    Raises RuntimeError when the active backend is not vision-capable
    (caller should catch and fall back to Tesseract OCR).
    """
    if not _is_vision_backend():
        raise RuntimeError(
            "Active LLM backend does not support vision. "
            "Falling back to Tesseract OCR."
        )

    try:
        import fitz
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(f"PDF rendering dependencies missing: {exc}") from exc

    tables: list[RawTable] = []
    doc = fitz.open(file_path)
    try:
        pages_to_do = min(len(doc), MAX_VISION_PAGES)
        log.info("vision_extract: %s — %d page(s) via gpt-4o-mini",
                 Path(file_path).name, pages_to_do)

        for page_num, page in enumerate(doc, start=1):
            if page_num > MAX_VISION_PAGES:
                break
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img_b64 = _page_to_base64(img)

            try:
                result = _call_vision_api(img_b64, page_num)
            except Exception as exc:
                log.warning("vision_extract page %d failed: %s", page_num, exc)
                continue

            for pg in result.get("pages", []):
                raw_periods = pg.get("periods") or []
                rows_data = pg.get("rows") or []
                stmt_type = pg.get("statement_type", "other")

                if not rows_data:
                    continue

                # Normalise all period strings
                periods: list[str] = []
                period_map: dict[str, str] = {}
                for p in raw_periods:
                    iso = _normalise_period(str(p))
                    key = iso or str(p)
                    periods.append(key)
                    period_map[str(p)] = key

                table_name = f"page{page_num}{_stmt_suffix(stmt_type)}"
                raw_rows: list[RawRow] = []

                for r_idx, row in enumerate(rows_data, start=1):
                    label = (row.get("label") or "").strip()
                    if not label:
                        continue
                    section = (row.get("section") or "").strip()
                    raw_vals = row.get("values") or {}

                    values: dict[str, float] = {}
                    for k, v in raw_vals.items():
                        iso_k = period_map.get(str(k)) or _normalise_period(str(k)) or str(k)
                        try:
                            values[iso_k] = float(v)
                        except (TypeError, ValueError):
                            values[iso_k] = 0.0

                    if not values:
                        continue

                    raw_rows.append(RawRow(
                        row_idx=r_idx,
                        label=label,
                        values=values,
                        source_ref={"image": table_name, "row": r_idx, "method": "vision_llm"},
                        section=section,
                    ))

                if raw_rows:
                    tables.append(RawTable(rows=raw_rows, periods=periods, name=table_name))

    finally:
        doc.close()

    log.info("vision_extract: %s — %d table(s) extracted", Path(file_path).name, len(tables))
    return tables
