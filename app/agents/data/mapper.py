from __future__ import annotations

import json
import re
from datetime import date, datetime

from app.agents.base import AgentResult, ArtifactRef, Status, TaskSpec, WorkerAgent
from app.agents.schemas import MappingItem, MappingSet
from app.domain.coa import ACCOUNT_STATEMENT, infer_statement_hint, lookup_synonym
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
        # this document's mapping (see orchestrator.apply_pending_instructions) -- None for
        # every job that never uses that feature, which is the common case.
        user_guidance = spec.params.get("user_guidance")
        doc = Document.query.get(document_id)

        payload = json.loads(storage.resolve(raw_table_uri).read_text())
        rows = payload["rows"]

        # Which statement this sheet/table IS, when unambiguous (Balance Sheet/P&L/Cash
        # Flow) -- scopes both the memory lookup and the rule/LLM mapping below to that
        # statement's accounts, so a Cash Flow Statement's non-cash add-back rows (which
        # reuse the exact label text of the corresponding P&L expense, e.g. "Depreciation
        # and amortisation expense") can't resolve to the P&L account and get summed into
        # it. See infer_statement_hint's docstring for the confirmed-live failure this fixes.
        statement_hint = infer_statement_hint(spec.params.get("table_name"))

        resolved: dict[int, tuple[str, float, str]] = {}  # row idx in `rows` -> (account_id, confidence, method)
        unresolved_labels = []
        unresolved_idx = []

        for i, row in enumerate(rows):
            existing = lookup_memory(spec.tenant_id, doc.layout_id, row["label"])
            if (existing and existing.confidence >= self.REVIEW_THRESHOLD
                    and (statement_hint is None or ACCOUNT_STATEMENT.get(existing.account_id) == statement_hint)):
                resolved[i] = (existing.account_id, existing.confidence, "memory")
                continue

            # Deterministic first (design doc §2 principle 3): a known-synonym match never
            # needs an LLM call at all.
            rule_account_id = lookup_synonym(row["label"], statement_hint)
            if rule_account_id:
                resolved[i] = (rule_account_id, RULE_MATCH_CONFIDENCE, "rule")
                write_memory(spec.tenant_id, doc.entity_id, doc.layout_id, row["label"],
                             rule_account_id, RULE_MATCH_CONFIDENCE, "rule")
            else:
                unresolved_labels.append(row["label"])
                unresolved_idx.append(i)

        if unresolved_labels:
            # The prompt (SCHEMA_MAPPER) says "from the allowed list given to you" -- that
            # list has to actually be in the prompt, or a real LLM has no way to know valid
            # account ids and will invent its own (confirmed against a live model: it
            # returned made-up ids like "1000"/"9999" when this list was missing).
            allowed_accounts = coa_lookup()
            if statement_hint is not None:
                # Same reasoning as the rule-match check above: don't let the LLM pick a
                # same-named-but-wrong-statement account either (e.g. a Cash Flow sheet's
                # "Finance costs" add-back resolving to the P&L expense account).
                scoped = [a for a in allowed_accounts if a["statement"] == statement_hint]
                allowed_accounts = scoped or allowed_accounts
            valid_ids = {a["id"] for a in allowed_accounts}
            # Check the data size FIRST and decide how to send it, rather than firing one
            # unbounded request regardless of volume -- confirmed live against a real sales
            # register-style sheet: 725 unresolved labels in a single call produced a prompt
            # large enough that OpenAI's response took longer than the 60s read timeout,
            # losing the ENTIRE batch to the fallback at once. Batching keeps each request a
            # bounded, fast size, and confines a single batch's failure to just that batch
            # instead of every unresolved label in the document.
            by_label: dict[str, MappingItem] = {}
            for batch_start in range(0, len(unresolved_labels), _MAX_LABELS_PER_LLM_CALL):
                batch = unresolved_labels[batch_start:batch_start + _MAX_LABELS_PER_LLM_CALL]
                user_content = (embed_json("ALLOWED_ACCOUNTS_JSON", allowed_accounts) + "\n"
                                + embed_json("LABELS_JSON", batch))
                if user_guidance:
                    user_content += "\n" + embed_json("USER_GUIDANCE_JSON", user_guidance)
                prompt = [
                    {"role": "system", "content": prompts.SCHEMA_MAPPER},
                    {"role": "user", "content": user_content},
                ]
                try:
                    mapping_set: MappingSet = self.call_llm(prompt, schema=MappingSet)
                except Exception as exc:
                    # LLM unreachable/exhausted its retries (e.g. sustained 503/timeout from
                    # an overloaded endpoint) -- degrade gracefully rather than failing the
                    # whole document (and losing the already-successful extraction with it,
                    # per the design doc's "fail loudly, degrade gracefully"). Every label in
                    # THIS batch falls through to the low-confidence BS.CA.OTHER placeholder
                    # below, same as an out-of-allowlist LLM answer, so it still lands as a
                    # review item -- other batches are unaffected.
                    import logging
                    logging.getLogger(__name__).warning(
                        "SchemaMapperAgent LLM call failed for document %s (batch %d-%d of "
                        "%d), falling back to low-confidence placeholders for %d label(s): %s",
                        document_id, batch_start, batch_start + len(batch), len(unresolved_labels),
                        len(batch), exc,
                    )
                    mapping_set = MappingSet(mappings=[])
                by_label.update({m.source_label: m for m in mapping_set.mappings})
            for i, label in zip(unresolved_idx, unresolved_labels):
                item = by_label.get(label)
                if item and item.account_id in valid_ids:
                    account_id, confidence = item.account_id, item.confidence
                else:
                    # Model returned nothing, or an id outside the allowed list -- treat as
                    # low-confidence rather than trusting a hallucinated account id.
                    account_id, confidence = "BS.CA.OTHER", 0.2
                resolved[i] = (account_id, confidence, "llm")
                write_memory(spec.tenant_id, doc.entity_id, doc.layout_id, label, account_id, confidence, "llm")

        fact_count = 0
        low_confidence: list[dict] = []
        unit_scale = float(doc.unit_scale or 1)

        for i, row in enumerate(rows):
            account_id, confidence, method = resolved[i]
            if confidence < self.REVIEW_THRESHOLD:
                low_confidence.append({
                    "document_id": doc.id, "label": row["label"], "suggested_account_id": account_id,
                    "confidence": confidence, "row_idx": row["row_idx"],
                })
            for period_str, value in row["values"].items():
                period_end = _parse_period(period_str)
                if period_end is None:
                    continue
                db.session.add(FinancialFact(
                    dataset_version=dataset_version_id, entity_id=doc.entity_id, account_id=account_id,
                    period_end=period_end, value=value * unit_scale, currency=doc.currency,
                    source_doc=doc.id, source_ref=row["source_ref"], confidence=confidence,
                ))
                fact_count += 1

        doc.status = "mapped"
        db.session.commit()

        return AgentResult(
            task_id=spec.task_id, status=Status.DONE,
            outputs=[ArtifactRef(id=doc.id, kind="dataset", uri="db://financial_facts", row_count=fact_count)],
            summary=f"Mapped {len(rows)} rows ({len(unresolved_labels)} via LLM) into {fact_count} facts "
                    f"for '{doc.original_filename}'",
            confidence=min([c for _, c, _ in resolved.values()], default=1.0),
            usage={"low_confidence_mappings": low_confidence},
        )
