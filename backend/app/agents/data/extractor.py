from __future__ import annotations

import json
import re
from datetime import date, datetime

from app.agents.base import AgentResult, ArtifactRef, Issue, Status, TaskSpec, WorkerAgent
from app.agents.schemas import ExtractedTableResult, TableBoundaryResult
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.models.bank import BankTransaction
from app.models.document import Document
from app.models.gst import GstReturn
from app.tools.parsers import RawRow, RawTable
from app.tools.parsers.csv_tool import read_bank_csv, read_csv
from app.tools.parsers.excel import read_excel
from app.tools.parsers.pdf import extract_pdf_tables, is_scanned_pdf
from app.tools.vector_search import index_document
from app.utils import storage

_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%m/%d/%Y"]
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "tiff", "tif", "bmp"}


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _safe_name(name: str) -> str:
    return _SAFE_NAME_RE.sub("_", name)[:60]


class ExtractorAgent(WorkerAgent):
    name = "extractor"
    allowed_tools = ["file.read", "excel.read_sheets", "excel.read_grid", "excel.read_bank",
                      "csv.read", "csv.read_tables", "csv.read_grid", "csv.read_bank",
                      "pdf.extract_tables", "pdf.extract_text", "ocr.page",
                      "ocr.extract_text", "ocr.extract_tables", "table.detect_header_row"]

    def execute(self, spec: TaskSpec) -> AgentResult:
        document_id = spec.params["document_id"]
        dataset_version_id = spec.params["dataset_version_id"]
        doc = Document.query.get(document_id)
        if doc is None:
            return AgentResult(task_id=spec.task_id, status=Status.FAILED, summary=f"Document {document_id} not found")

        ext = doc.original_filename.lower().rsplit(".", 1)[-1]
        abs_path = str(storage.resolve(doc.file_uri))

        try:
            if doc.doc_type == "bank_statement":
                if ext in ("xlsx", "xls"):
                    return self._extract_bank(spec, doc, abs_path, dataset_version_id, is_excel=True)
                elif ext in ("csv", "tsv", "txt"):
                    return self._extract_bank(spec, doc, abs_path, dataset_version_id, is_excel=False)
            if doc.doc_type in ("gstr_3b", "gstr_2b"):
                if ext in ("xlsx", "xls"):
                    return self._extract_gst(spec, doc, abs_path, dataset_version_id, is_excel=True)
                elif ext in ("csv", "tsv"):
                    return self._extract_gst(spec, doc, abs_path, dataset_version_id, is_excel=False)
            return self._extract_statement(spec, doc, ext, abs_path)
        except Exception as exc:
            doc.status = "extraction_failed"
            db.session.commit()
            return AgentResult(
                task_id=spec.task_id, status=Status.FAILED,
                summary=f"Extraction failed for '{doc.original_filename}': {exc}",
                issues=[Issue(severity="error", code="EXTRACTION_FAILED", message=str(exc))],
            )

    def _index_for_rag(self, doc, text: str) -> None:
        """Best-effort: indexes extracted text for the QA agent's document_rag route
        (tools/vector_search.py). Never fails the extraction over an indexing hiccup."""
        try:
            if text.strip():
                index_document(doc.tenant_id, doc.id, text)
        except Exception:
            pass

    def _llm_header_row(self, preview: list[list]) -> int | None:
        """Escalates to the LLM only when the deterministic heuristic couldn't find a
        confident header row (see tools/table_detect.py) -- e.g. a metadata block that's
        itself table-shaped enough to fool the heuristic."""
        prompt = [
            {"role": "system", "content": prompts.TABLE_BOUNDARY_DETECTOR},
            {"role": "user", "content": embed_json("ROWS_PREVIEW_JSON", preview)},
        ]
        try:
            result: TableBoundaryResult = self.call_llm(prompt, schema=TableBoundaryResult)
        except Exception:
            return None
        if 0 <= result.header_row_idx < len(preview):
            return result.header_row_idx
        return None

    def _llm_extract_table(self, ocr_text: str) -> RawTable | None:
        """Fallback to LLM when deterministic OCR table clustering yields no clean rows."""
        prompt = [
            {"role": "system", "content": prompts.TABLE_EXTRACTOR},
            {"role": "user", "content": f"OCR Text:\n{ocr_text[:6000]}"},
        ]
        try:
            res: ExtractedTableResult = self.call_llm(prompt, schema=ExtractedTableResult)
        except Exception:
            return None

        if not res or not res.rows or not res.periods:
            return None

        raw_rows = []
        for idx, r in enumerate(res.rows, start=1):
            if not r.label or not r.values:
                continue
            raw_rows.append(RawRow(
                row_idx=idx,
                label=r.label,
                values=r.values,
                source_ref={"source": "llm_ocr_recovery", "row": idx},
                section=r.section,
            ))
        if raw_rows:
            return RawTable(rows=raw_rows, periods=res.periods, name="ocr_table")
        return None

    def _extract_bank(self, spec, doc, abs_path, dataset_version_id, is_excel: bool = False) -> AgentResult:
        if is_excel:
            transactions = self.call_tool("excel.read_bank", file_path=abs_path)
        else:
            transactions = self.call_tool("csv.read_bank", file_path=abs_path)
        count = 0
        lines = []
        for t in transactions:
            txn_date = _parse_date(t["txn_date"])
            if txn_date is None:
                continue
            db.session.add(BankTransaction(
                dataset_version=dataset_version_id, txn_date=txn_date, narration=t["narration"],
                debit=t["debit"], credit=t["credit"], balance=t["balance"],
                source_doc=doc.id, source_ref=t["source_ref"],
            ))
            lines.append(f"{txn_date.isoformat()}: {t['narration']} debit={t['debit']} credit={t['credit']} "
                         f"balance={t['balance']}")
            count += 1
        doc.status = "extracted"
        db.session.commit()
        self._index_for_rag(doc, "\n".join(lines))
        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=doc.id, kind="dataset", uri="db://bank_transactions", row_count=count)],
            summary=f"Extracted {count} bank transactions from '{doc.original_filename}'", confidence=0.95,
        )

    def _extract_gst(self, spec, doc, abs_path, dataset_version_id, is_excel: bool = False) -> AgentResult:
        if is_excel:
            sheets = self.call_tool("excel.read_sheets", file_path=abs_path)
            table = next((info["table"] for info in sheets.values() if info.get("table")), None)
        else:
            table = self.call_tool("csv.read", file_path=abs_path)
        return_type = "GSTR3B" if doc.doc_type == "gstr_3b" else "GSTR2B"
        count = 0
        lines = []
        if table and getattr(table, "rows", None):
            for row in table.rows:
                for period_str, value in row.values.items():
                    period = _parse_date(period_str) or doc.period_end
                    if period is None:
                        continue
                    db.session.add(GstReturn(
                        dataset_version=dataset_version_id, return_type=return_type, period=period,
                        field=row.label, value=value, source_doc=doc.id, source_ref=row.source_ref,
                    ))
                    count += 1
                lines.append(f"{row.label}: {row.values}")
        doc.status = "extracted"
        db.session.commit()
        self._index_for_rag(doc, "\n".join(lines))
        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=doc.id, kind="dataset", uri="db://gst_returns", row_count=count)],
            summary=f"Extracted {count} {return_type} fields from '{doc.original_filename}'", confidence=0.9,
        )

    def _extract_statement(self, spec, doc, ext, abs_path) -> AgentResult:
        """Every sheet (Excel) / every extracted table (PDF) is processed, not just the
        first -- a single file commonly carries P&L/BS/CF as separate sheets or tables."""
        tables: list = []

        if ext in ("xlsx", "xls"):
            sheets = self.call_tool("excel.read_sheets", file_path=abs_path)
            low_confidence = [name for name, info in sheets.items() if not info["confident"]]
            if low_confidence:
                grids = self.call_tool("excel.read_grid", file_path=abs_path)
                overrides = {}
                for name in low_confidence:
                    idx = self._llm_header_row(grids.get(name, []))
                    if idx is not None:
                        overrides[name] = idx
                if overrides:
                    sheets = self.call_tool("excel.read_sheets", file_path=abs_path, header_overrides=overrides)
            tables = [info["table"] for info in sheets.values()]
        elif ext == "csv":
            grid = self.call_tool("csv.read_grid", file_path=abs_path)
            header_idx = self.call_tool("table.detect_header_row", grid=grid)
            if header_idx is None:
                header_idx = self._llm_header_row(grid)
            tables = self.call_tool("csv.read_tables", file_path=abs_path, header_row_idx=header_idx)
            if not tables:
                table = self.call_tool("csv.read", file_path=abs_path, header_row_idx=header_idx)
                tables = [table] if table else []
        elif ext in _IMAGE_EXTS:
            try:
                tables = self.call_tool("ocr.extract_tables", file_path=abs_path)
            except Exception:
                tables = []
        elif ext == "pdf":
            if is_scanned_pdf(abs_path):
                try:
                    tables = self.call_tool("ocr.extract_tables", file_path=abs_path)
                except Exception as exc:
                    tables = self.call_tool("pdf.extract_tables", file_path=abs_path)
                    if not tables:
                        doc.status = "needs_ocr"
                        db.session.commit()
                        return AgentResult(
                            task_id=spec.task_id, status=Status.PARTIAL,
                            summary=f"'{doc.original_filename}' looks like a scanned PDF; OCR table extraction failed: {exc}",
                            issues=[Issue(severity="warn", code="SCANNED_PDF", message=str(exc))],
                        )
            else:
                tables = self.call_tool("pdf.extract_tables", file_path=abs_path)
                if not tables:
                    try:
                        tables = self.call_tool("ocr.extract_tables", file_path=abs_path)
                    except Exception:
                        pass

        # If tables is still empty for image or PDF, try LLM table recovery from OCR text
        if not tables and ext in (_IMAGE_EXTS | {"pdf"}):
            try:
                ocr_text = self.call_tool("ocr.extract_text", file_path=abs_path, max_pages=3)
                if ocr_text.strip():
                    llm_table = self._llm_extract_table(ocr_text)
                    if llm_table and llm_table.rows:
                        tables = [llm_table]
            except Exception:
                pass

        tables = [t for t in tables if t and t.rows]
        if not tables:
            doc.status = "extraction_failed"
            db.session.commit()
            return AgentResult(
                task_id=spec.task_id, status=Status.PARTIAL,
                summary=f"No tabular data found in '{doc.original_filename}'",
                issues=[Issue(severity="warn", code="NO_TABLE_FOUND", message="Parser returned no rows")],
            )

        outputs: list[ArtifactRef] = []
        rag_lines: list[str] = []
        total_rows = 0
        for table in tables:
            rows_payload = [{
                "row_idx": r.row_idx, "label": r.label, "values": r.values,
                "is_subtotal": r.is_subtotal, "indent_level": r.indent_level, "source_ref": r.source_ref,
                "section": getattr(r, "section", ""),
            } for r in table.rows]
            artifact_uri = storage.write_text(
                f"{spec.job_id}/raw/{doc.id}_{_safe_name(table.name)}.json",
                json.dumps({"periods": table.periods, "rows": rows_payload}),
            )
            outputs.append(ArtifactRef(
                id=f"{doc.id}:{table.name}", kind="table", uri=artifact_uri,
                schema_summary=f"sheet/table={table.name} periods={table.periods}", row_count=len(rows_payload),
            ))
            rag_lines.extend(f"{r['label']}: {r['values']}" for r in rows_payload)
            total_rows += len(rows_payload)

        doc.status = "extracted"
        db.session.commit()
        self._index_for_rag(doc, "\n".join(rag_lines))

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE, outputs=outputs,
            summary=f"Extracted {total_rows} row(s) across {len(tables)} table(s) from '{doc.original_filename}'",
            confidence=0.9,
        )
