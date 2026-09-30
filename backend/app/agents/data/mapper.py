from __future__ import annotations

import json
import re
from datetime import date, datetime

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import MappingItem, MappingSet
from app.domain.coa import (ACCOUNT_STATEMENT, UNMAPPED, contextual_account, infer_statement_hint,
                            is_total_label, lookup_prefix_synonym, lookup_synonym, normalize_label,
                            section_other_bucket, sheet_role, strip_label_noise)
from app.extensions import db
from app.llm_gateway import prompts
from app.llm_gateway.prompt_utils import embed_json
from app.memory.mapping_memory import coa_lookup, lookup_memory, write_memory
from app.models.dataset import FinancialFact
from app.models.document import Document
from app.utils import storage

RULE_MATCH_CONFIDENCE = 0.95
# Keeps each schema-mapping LLM request a bounded, fast size regardless of how many
# unresolved labels a document has -- see the batching loop in execute() for why.
_MAX_LABELS_PER_LLM_CALL = 40

_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d",
    "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"
]


def _parse_period(value: str) -> date | None:
    if not value:
        return None
    s = str(value).strip()

    # 1. Direct match with standard formats
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    # 2. Strip common financial statement prefixes ('As at', 'Year ended', etc.)
    cleaned = re.sub(
        r"^(?:as\s+at|as\s+on|year\s+ended|for\s+the\s+year\s+ended|period\s+ended|quarter\s+ended)\s+",
        "", s, flags=re.IGNORECASE
    ).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass

    # 3. Match Month Day, Year e.g. 'Mar 31, 2026' or 'March 31, 2026'
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", cleaned)
    if m:
        month_str, day_str, year_str = m.groups()
        for mfmt in ("%b", "%B"):
            try:
                dt = datetime.strptime(f"{month_str} {day_str} {year_str}", f"{mfmt} %d %Y")
                return dt.date()
            except ValueError:
                pass

    # 4. Match Day Month Year e.g. '31 Mar 2026' or '31st March 2026'
    m2 = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9}),?\s+(\d{4})", cleaned)
    if m2:
        day_str, month_str, year_str = m2.groups()
        for mfmt in ("%b", "%B"):
            try:
                dt = datetime.strptime(f"{day_str} {month_str} {year_str}", f"%d {mfmt} %Y")
                return dt.date()
            except ValueError:
                pass

    # 5. Match Fiscal year range like 'FY2025-26', 'FY 2025-2026', 'FY25-26', '2025-26'
    m_fy = re.search(r"(?:FY\s*)?(\d{2,4})[-–/](\d{2,4})", cleaned, re.IGNORECASE)
    if m_fy:
        y1, y2 = m_fy.groups()
        end_year = int(y2)
        if end_year < 100:
            start_century = str(y1)[:2] if len(str(y1)) == 4 else "20"
            end_year = int(f"{start_century}{int(y2):02d}")
        return date(end_year, 3, 31)

    # 6. Match 'FY2026' or 'FY26'
    m_fy_single = re.search(r"FY\s*(\d{2,4})", cleaned, re.IGNORECASE)
    if m_fy_single:
        y = int(m_fy_single.group(1))
        if y < 100:
            y += 2000
        return date(y, 3, 31)

    # 7. Match bare 4-digit year e.g. '2026'
    m_year = re.search(r"\b(20\d{2}|19\d{2})\b", cleaned)
    if m_year:
        return date(int(m_year.group(1)), 3, 31)

    return None


class SchemaMapperAgent(WorkerAgent):
    name = "schema_mapper"
    allowed_tools = ["coa.lookup", "mapping.memory", "vector.search"]
    REVIEW_THRESHOLD = 0.85

    def execute(self, spec: TaskSpec) -> AgentResult:
        document_id = spec.params["document_id"]
        dataset_version_id = spec.params["dataset_version_id"]
        raw_table_uri = spec.params["raw_table_uri"]
        # Set only when the orchestrator decided a user's mid-run instruction applies to
        # this document's mapping (see orchestrator.apply_pending_instructions).
        user_guidance = spec.params.get("user_guidance")
        doc = Document.query.get(document_id)

        payload = json.loads(storage.resolve(raw_table_uri).read_text())
        rows = payload["rows"]
        table_name = spec.params.get("table_name")
        table_name = None if table_name in (None, "csv") else table_name

        # Which statement this sheet IS, when unambiguous from its name -- scopes every
        # lookup below to that statement's accounts, so a cash flow sheet's add-back rows
        # ("Depreciation and amortisation expense") can't land in the P&L account.
        statement_hint = infer_statement_hint(table_name)

        resolved: dict[int, tuple[str, float, str]] = {}  # row idx -> (account_id, confidence, method)
        for i, row in enumerate(rows):
            hit = self._deterministic(row, statement_hint)
            if hit:
                resolved[i] = hit

        # Primary statement vs supporting schedule (notes, ageing, loan lists, tax filings).
        # Supporting rows only ever confirm statement lines; they're never added into them.
        role = sheet_role(table_name, doc.doc_type, {acc for acc, _c, _m in resolved.values()})

        unresolved_idx: list[int] = []
        for i, row in enumerate(rows):
            if i in resolved:
                continue
            label = row["label"]
            if _GENERIC_SUBTOTAL.match(normalize_label(label)):
                resolved[i] = (UNMAPPED, 1.0, "subtotal")  # 'Subtotal' says nothing about its account
                continue
            if role == "supporting":
                resolved[i] = (UNMAPPED, 1.0, "supporting")
                continue
            if statement_hint == "CF":
                # The canonical cash-flow accounts are only section totals and cash lines (all
                # rule-matched); an adjustment row must not be guessed into CF.OPERATING.
                resolved[i] = (UNMAPPED, 1.0, "cf_detail")
                continue
            if statement_hint in (None, "BS") and not is_total_label(label):
                bucket = section_other_bucket(row.get("section"))
                if bucket:
                    # An unrecognised line inside a known balance-sheet section belongs to that
                    # section's 'other' bucket -- decided by structure, not guessed.
                    resolved[i] = (bucket, 0.9, "section")
                    continue
            existing = lookup_memory(spec.tenant_id, doc.layout_id, label)
            if (existing and existing.confidence >= self.REVIEW_THRESHOLD and existing.account_id in ACCOUNT_STATEMENT
                    and (statement_hint is None or ACCOUNT_STATEMENT.get(existing.account_id) == statement_hint)):
                resolved[i] = (existing.account_id, existing.confidence, "memory")
                continue
            unresolved_idx.append(i)

        llm_calls = 0
        if unresolved_idx:
            allowed_accounts = coa_lookup()
            if statement_hint is not None:
                scoped = [a for a in allowed_accounts if a["statement"] == statement_hint]
                allowed_accounts = scoped or allowed_accounts
            valid_ids = {a["id"] for a in allowed_accounts}
            allowed_accounts = allowed_accounts + [{"id": UNMAPPED, "name": "Not a ledger line (disclosure, "
                                                    "breakdown, ratio, count or duplicate subtotal)", "statement": "-"}]
            # Each label goes to the model with its section, so repeated captions ('Other
            # assets' under non-current vs current) are distinguishable -- and keyed back by
            # that exact text.
            texts = {i: _label_with_context(rows[i]) for i in unresolved_idx}
            unique_texts = list(dict.fromkeys(texts.values()))
            by_text: dict[str, MappingItem] = {}
            for batch_start in range(0, len(unique_texts), _MAX_LABELS_PER_LLM_CALL):
                batch = unique_texts[batch_start:batch_start + _MAX_LABELS_PER_LLM_CALL]
                user_content = (embed_json("ALLOWED_ACCOUNTS_JSON", allowed_accounts) + "\n"
                                + embed_json("LABELS_JSON", batch))
                if user_guidance:
                    user_content += "\n" + embed_json("USER_GUIDANCE_JSON", user_guidance)
                prompt = [{"role": "system", "content": prompts.SCHEMA_MAPPER},
                          {"role": "user", "content": user_content}]
                llm_calls += 1
                try:
                    mapping_set: MappingSet = self.call_llm(prompt, schema=MappingSet)
                except Exception as exc:
                    # Degrade gracefully: this batch's rows fall back below, other batches are unaffected.
                    import logging
                    logging.getLogger(__name__).warning(
                        "SchemaMapperAgent LLM call failed for document %s (batch at %d): %s",
                        document_id, batch_start, exc)
                    mapping_set = MappingSet(mappings=[])
                by_text.update({m.source_label: m for m in mapping_set.mappings})
            for i in unresolved_idx:
                item = by_text.get(texts[i]) or by_text.get(rows[i]["label"])
                if item and (item.account_id in valid_ids or item.account_id == UNMAPPED):
                    account_id, confidence = item.account_id, item.confidence
                else:
                    # No answer, or an invented id: never guess an account. The row is left out
                    # of the ledger and surfaced for review instead of silently skewing a total.
                    account_id, confidence = UNMAPPED, 0.2
                resolved[i] = (account_id, confidence, "llm")
                if account_id != UNMAPPED and confidence >= self.REVIEW_THRESHOLD and not _is_contextual(rows[i]):
                    write_memory(spec.tenant_id, doc.entity_id, doc.layout_id, rows[i]["label"], account_id,
                                 confidence, "llm")

        fact_count = 0
        unmapped = 0
        low_confidence: list[dict] = []
        unit_scale = float(doc.unit_scale or 1)

        for i, row in enumerate(rows):
            account_id, confidence, method = resolved[i]
            if account_id == UNMAPPED:
                unmapped += 1
                if method == "llm" and confidence < self.REVIEW_THRESHOLD and role == "primary":
                    low_confidence.append({"document_id": doc.id, "label": row["label"], "section": row.get("section"),
                                           "suggested_account_id": None, "confidence": confidence,
                                           "row_idx": row["row_idx"], "sheet_role": role})
                continue
            if confidence < self.REVIEW_THRESHOLD:
                low_confidence.append({
                    "document_id": doc.id, "label": row["label"], "section": row.get("section"),
                    "suggested_account_id": account_id, "confidence": confidence, "row_idx": row["row_idx"],
                    "sheet_role": role,
                })
            source_ref = {**(row.get("source_ref") or {}), "label": row["label"], "section": row.get("section") or "",
                          "role": role, "method": method, "is_total": is_total_label(row["label"])}
            for period_str, value in row["values"].items():
                period_end = _parse_period(period_str)
                if period_end is None:
                    continue
                db.session.add(FinancialFact(
                    dataset_version=dataset_version_id, entity_id=doc.entity_id, account_id=account_id,
                    period_end=period_end, value=value * unit_scale, currency=doc.currency,
                    source_doc=doc.id, source_ref=source_ref, confidence=confidence,
                ))
                fact_count += 1

        doc.status = "mapped"
        db.session.commit()

        mapped_conf = [c for a, c, _ in resolved.values() if a != UNMAPPED]
        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=doc.id, kind="dataset", uri="db://financial_facts", row_count=fact_count)],
            summary=f"{role.title()} table '{table_name or doc.original_filename}': mapped {len(rows) - unmapped} of "
                    f"{len(rows)} rows into {fact_count} facts ({len(unresolved_idx)} via LLM in {llm_calls} call(s), "
                    f"{unmapped} left out as disclosures/breakdowns)",
            confidence=min(mapped_conf, default=1.0),
            usage={"low_confidence_mappings": low_confidence, "sheet_role": role},
        )

    @staticmethod
    def _deterministic(row: dict, statement_hint: str | None) -> tuple[str, float, str] | None:
        """Section-aware rule, then exact synonym, then multi-word prefix synonym."""
        label, section = row["label"], row.get("section")
        account = contextual_account(label, section, statement_hint)
        if account:
            return account, RULE_MATCH_CONFIDENCE, "context"
        account = lookup_synonym(label, statement_hint)
        if account:
            return account, RULE_MATCH_CONFIDENCE, "rule"
        account = lookup_prefix_synonym(label, statement_hint)
        if account:
            return account, 0.9, "prefix"
        return None


_GENERIC_SUBTOTAL = re.compile(r"^(?:sub[- ]?total|total|grand total|net)$")


def _label_with_context(row: dict) -> str:
    section = (row.get("section") or "").strip()
    return f"{row['label']}  [section: {section}]" if section else row["label"]


def _is_contextual(row: dict) -> bool:
    # A label whose meaning depends on its section must not be memorised label-only.
    return bool(row.get("section")) and normalize_label(strip_label_noise(row["label"])) in {
        "borrowings", "other assets", "other liabilities", "provisions", "investments", "loans",
        "other financial assets", "other financial liabilities", "lease liabilities", "derivative assets",
        "derivative liabilities", "deferred income", "retirement benefit obligations"}
