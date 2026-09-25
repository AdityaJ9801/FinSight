from __future__ import annotations

from datetime import date
from pathlib import Path

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import ClassificationResult
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.document import DOC_TYPES, Document
from app.tools.parsers.csv_tool import sniff_csv_headers
from app.utils import storage


_PREVIEW_HEAD = 20
_PREVIEW_TAIL = 10


def _head_tail_preview(lines: list[str], head: int = _PREVIEW_HEAD, tail: int = _PREVIEW_TAIL) -> str:
    """Metadata (company name, report title, unit notes) and closing notes/footnotes can
    both carry classification signal, and a real table's structure isn't visible from a
    handful of lines at the very top alone -- so this samples the start AND the end of the
    document rather than truncating to a fixed head. Small files are sent whole."""
    lines = [ln for ln in lines if ln.strip()]
    if len(lines) <= head + tail:
        return "\n".join(lines)
    omitted = len(lines) - head - tail
    return "\n".join(lines[:head]) + f"\n... [{omitted} lines omitted] ...\n" + "\n".join(lines[-tail:])


class IntakeAgent(WorkerAgent):
    name = "intake_classifier"
    allowed_tools = ["pdf.extract_text", "layout.fingerprint"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        document_id = spec.params["document_id"]
        doc = Document.query.get(document_id)
        if doc is None:
            return AgentResult(task_id=spec.task_id, status=Status.FAILED, summary=f"Document {document_id} not found")

        ext = doc.original_filename.lower().rsplit(".", 1)[-1]
        abs_path = str(storage.resolve(doc.file_uri))
        text_excerpt = ""
        headers: list[str] = []

        try:
            if ext == "pdf":
                full_text = self.call_tool("pdf.extract_text", file_path=abs_path, max_pages=10)
                text_excerpt = _head_tail_preview(full_text.splitlines())
            elif ext == "csv":
                headers = sniff_csv_headers(abs_path)
                # Header alone is often just column labels ("Line Item", period dates) with
                # no signal about statement type -- sampling real rows (start and end) gives
                # the classifier something to actually match against.
                lines = Path(abs_path).read_text(encoding="utf-8-sig").splitlines()
                text_excerpt = _head_tail_preview(lines)
            elif ext in ("xlsx", "xls"):
                import openpyxl

                wb = openpyxl.load_workbook(abs_path, read_only=True, data_only=True)
                headers = wb.sheetnames
                sheet_previews = []
                for ws in wb.worksheets:
                    sheet_lines = [
                        ", ".join(str(c) for c in row if c not in (None, ""))
                        for row in ws.iter_rows(max_row=15, values_only=True)
                    ]
                    sheet_previews.append(f"[Sheet: {ws.title}]\n" + _head_tail_preview(sheet_lines, head=15, tail=5))
                text_excerpt = "\n\n".join(sheet_previews)
                wb.close()
        except Exception as exc:  # parser failure -> classify as "other", let extraction fail loudly later
            text_excerpt = f"(could not read file for preview: {exc})"

        prompt = [
            {"role": "system", "content": prompts.INTAKE_CLASSIFIER},
            {"role": "user", "content": embed_json("ALLOWED_DOC_TYPES_JSON", list(DOC_TYPES)) + "\n"
                                         + f"Filename: {doc.original_filename}\nExcerpt:\n{text_excerpt[:8000]}"},
        ]
        # mask_pii=True: this prompt carries a raw excerpt of the uploaded document, unlike
        # most other agents' calls which only send our own structured JSON (see base.py).
        result: ClassificationResult = self.call_llm(prompt, schema=ClassificationResult, mask_pii=True)

        # A real LLM not shown the allowed values will happily invent a human-readable
        # string ("Profit and Loss Statement") instead of the enum code ("pnl") -- caught
        # against a live model. "other" still gets mapped (see _NEEDS_MAPPING), so this is
        # a safe fallback rather than silently accepting a value nothing else recognizes.
        doc.doc_type = result.doc_type if result.doc_type in DOC_TYPES else "other"
        doc.unit_scale = result.unit_scale
        doc.currency = result.currency
        for attr, value in (("period_start", result.period_start), ("period_end", result.period_end)):
            if value:
                try:
                    setattr(doc, attr, date.fromisoformat(value))
                except ValueError:
                    pass
        if headers:
            doc.layout_id = self.call_tool("layout.fingerprint", labels=headers)
        doc.status = "classified"
        db.session.commit()

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=doc.id, kind="raw_file", uri=doc.file_uri)],
            summary=f"Classified '{doc.original_filename}' as {result.doc_type} (confidence {result.confidence:.2f})",
            confidence=result.confidence,
        )
