"""OCR for scanned PDFs/images. Opt-in via OCR_ENABLED because it requires the Tesseract
binary installed separately from pip (design doc's "self-hosted OCR" option). Degrades
with a clear error rather than a confusing stack trace when it isn't set up.
"""
from __future__ import annotations

from app.tools.registry import tool


class OcrNotAvailableError(Exception):
    pass


def ocr_pdf(file_path: str, enabled: bool = False) -> str:
    if not enabled:
        raise OcrNotAvailableError(
            "OCR_ENABLED is false. This looks like a scanned PDF with no text layer. "
            "Install Tesseract (https://github.com/tesseract-ocr/tesseract) and set "
            "OCR_ENABLED=true to process scanned documents."
        )
    try:
        import fitz  # PyMuPDF, used only to rasterize pages -- no poppler dependency
        import pytesseract
        from PIL import Image
        import io
    except ImportError as exc:
        raise OcrNotAvailableError(f"OCR dependencies not installed: {exc}") from exc

    text_parts = []
    doc = fitz.open(file_path)
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text_parts.append(pytesseract.image_to_string(img))
    finally:
        doc.close()
    return "\n".join(text_parts)


tool("ocr.page", allowed_agents=["extractor"])(ocr_pdf)
