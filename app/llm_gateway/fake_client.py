"""Deterministic stand-in for a real LLM, used when LLM_BACKEND=fake (the default until a
real custom endpoint is wired up). It does not "understand" text -- it pattern-matches on
keywords and on the tagged JSON blobs agents embed via prompt_utils.embed_json, so the
rest of the system (tool calls, reconciliation, metrics, report binding) can be built and
tested end-to-end before real credentials exist. See app/agents/schemas.py for the shapes
it fills in.
"""
from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel

from app.agents import schemas as sch
from app.domain.coa import lookup_synonym
from app.llm_gateway.base import LLMGateway
from app.llm_gateway.prompt_utils import all_message_text, extract_json, last_user_text

T = TypeVar("T", bound=BaseModel)


class FakeLLMGateway(LLMGateway):
    def complete(self, messages, schema: Type[T] | None = None, tier: str = "default", max_retries: int = 1):
        text = all_message_text(messages)
        # Keyword heuristics (_classify, _route) must only look at what the USER actually
        # said, not the system prompt's own prose describing the possible categories --
        # see prompt_utils.last_user_text's docstring for why that's not just pedantry.
        user_low = last_user_text(messages).lower()

        if schema is None:
            return "This is a canned response from the fake LLM gateway (LLM_BACKEND=fake)."

        if schema is sch.ClassificationResult:
            return sch.ClassificationResult(**_classify(user_low))
        if schema is sch.MappingSet:
            return sch.MappingSet(mappings=_map_labels(text))
        if schema is sch.ExplanationResult:
            return sch.ExplanationResult(
                explanation="Deterministic checks flagged a discrepancy; see validation_results for the exact diff.",
                likely_cause="Likely a mapping or period-alignment issue in the source document.",
            )
        if schema is sch.FindingsSet:
            return sch.FindingsSet(findings=_generic_findings(text))
        if schema is sch.InsightSet:
            return sch.InsightSet(insights=_insights_from_metrics(text))
        if schema is sch.ChartCaptionSet:
            return sch.ChartCaptionSet(captions=_chart_captions(text))
        if schema is sch.ReportDraftResult:
            return sch.ReportDraftResult(**_report_draft(text))
        if schema is sch.VerifierVerdict:
            return sch.VerifierVerdict(passed=True, claim_feedback=[])
        if schema is sch.RouteDecision:
            return sch.RouteDecision(route=_route(user_low))
        if schema is sch.QAAnswerResult:
            return sch.QAAnswerResult(**_qa_answer(text))
        if schema is sch.InstructionInterpretation:
            return sch.InstructionInterpretation(**_interpret_instruction(text))
        if schema is sch.AssistantDecision:
            return sch.AssistantDecision(**_assistant_decision(text))

        return _generic_instance(schema)

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Cheap, deterministic bag-of-hashes "embedding" -- good enough for wiring/tests.
        import hashlib

        vectors = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vectors.append([b / 255.0 for b in h[:32]])
        return vectors


def _classify(low: str) -> dict:
    if "narration" in low and ("debit" in low or "credit" in low) and "balance" in low:
        doc_type = "bank_statement"
    elif "gstr-3b" in low or "gstr3b" in low:
        doc_type = "gstr_3b"
    elif "gstr-2b" in low or "gstr2b" in low:
        doc_type = "gstr_2b"
    elif "trial balance" in low:
        doc_type = "trial_balance"
    elif "balance sheet" in low or "total equity and liabilities" in low:
        doc_type = "balance_sheet"
    elif "profit and loss" in low or "revenue from operations" in low or "p&l" in low:
        doc_type = "pnl"
    elif "ageing" in low and ("receivable" in low or "debtor" in low):
        doc_type = "ageing_ar"
    elif "ageing" in low and ("payable" in low or "creditor" in low):
        doc_type = "ageing_ap"
    else:
        doc_type = "other"

    if "lakh" in low:
        unit_scale = 100000
    elif "crore" in low:
        unit_scale = 10000000
    elif "'000" in low or "thousand" in low:
        unit_scale = 1000
    else:
        unit_scale = 1

    return {"doc_type": doc_type, "unit_scale": unit_scale, "currency": "INR", "confidence": 0.9}


def _map_labels(text: str) -> list[dict]:
    labels = extract_json("LABELS_JSON", text) or []
    out = []
    for label in labels:
        account_id = lookup_synonym(label)
        if account_id:
            out.append({"source_label": label, "account_id": account_id, "confidence": 0.9})
        else:
            out.append({"source_label": label, "account_id": "BS.CA.OTHER", "confidence": 0.3})
    return out


def _generic_findings(text: str) -> list[dict]:
    metrics = extract_json("METRICS_JSON", text) or []
    findings = []
    for m in metrics[:3]:
        code = m.get("metric_code") or m.get("code") or "metric"
        period = m.get("period_end", "")
        findings.append({
            "title": f"{code.replace('_', ' ').title()} observation",
            "body": f"{{{{m:{code}:{period}}}}} was computed for the period; review against prior periods.",
            "severity": "info",
            "metric_ids": [m.get("id", code)],
        })
    return findings


def _insights_from_metrics(text: str) -> list[dict]:
    metrics = extract_json("METRICS_JSON", text) or []
    insights = []
    for m in metrics[:5]:
        code = m.get("metric_code") or m.get("code") or "metric"
        period = m.get("period_end", "")
        mid = m.get("id", code)
        insights.append({
            "title": f"{code.replace('_', ' ').title()} trend",
            "body": f"{{{{m:{code}:{period}}}}} is the latest reading for this metric.",
            "metric_ids": [mid],
            "recommendation": f"Monitor {code.replace('_', ' ')} over the next period.",
        })
    if not insights:
        insights.append({
            "title": "Insufficient data",
            "body": "Not enough validated metrics were available to generate insights.",
            "metric_ids": [],
            "recommendation": None,
        })
    return insights


def _chart_captions(text: str) -> list[dict]:
    charts = extract_json("CHARTS_JSON", text) or []
    return [
        {"chart_id": c.get("chart_id", ""), "caption": f"{c.get('title', 'This chart')} over the periods shown."}
        for c in charts if c.get("chart_id")
    ]


def _report_draft(text: str) -> dict:
    skeleton = extract_json("SKELETON_JSON", text) or []
    insights = extract_json("INSIGHTS_JSON", text) or []
    charts = extract_json("CHARTS_JSON", text) or []
    chart_ids = [c.get("chart_id") for c in charts if c.get("chart_id")]

    if skeleton:
        sections = []
        for i, sk in enumerate(skeleton):
            ins_body = insights[i].get("body", "") if i < len(insights) else ""
            guide = sk.get("diagnostic_guide") or []
            if guide and not ins_body:
                metric_name = guide[0].get("canonical_name", "key metrics")
                cfo_q = guide[0].get("sample_questions", ["Review operational drivers."])[0]
                body_text = (
                    f"Analysis and root-cause evaluation for {sk.get('heading', 'this section')} based on validated metrics. "
                    f"Virtual CFO Diagnostic Guidance: Monitor {metric_name} and investigate operational drivers. "
                    f"Management Action Point: {cfo_q}"
                )
            else:
                body_text = ins_body or f"Analysis and evaluation for {sk.get('heading', 'this section')} based on validated metrics."

            matched_charts = [cid for cid in sk.get("chart_ids", []) if cid]
            if not matched_charts and chart_ids and i < len(chart_ids):
                matched_charts = [chart_ids[i]]
            sections.append({
                "heading": sk.get("heading", f"Section {i+1}"),
                "body": body_text,
                "section_key": sk.get("section_key"),
                "kind": "narrative",
                "chart_ids": matched_charts,
            })
        return {"title": "Financial Analysis Report", "sections": sections}

    sections = [
        {"heading": "Executive Summary", "body": "This report summarizes the entity's financial position based on validated data.", "section_key": "executive_summary", "kind": "narrative", "chart_ids": []}
    ]
    for ins in insights[:8]:
        sections.append({"heading": ins.get("title", "Insight"), "body": ins.get("body", ""), "section_key": "insight", "kind": "narrative", "chart_ids": []})
    if len(sections) == 1:
        sections.append({"heading": "Findings", "body": "No material findings were generated for this period.", "section_key": "findings", "kind": "narrative", "chart_ids": []})
    return {"title": "Financial Analysis Report", "sections": sections}


def _route(low: str) -> str:
    if any(k in low for k in ("chart", "graph", "plot", "visualization", "cost structure")):
        return "chart_lookup"
    if any(k in low for k in ("redo", "recompute", "rerun", "re-run", "recalculate", "regenerate")):
        return "action_request"
    if any(k in low for k in ("what does", "says", "mentioned in the document", "per the document")):
        return "document_rag"
    if any(k in low for k in ("report", "recommendation", "insight", "health score", "summary", "overview")):
        return "report_lookup"
    if any(k in low for k in ("ratio", "how much", "total", "value of", "trend", "compare")):
        return "sql"
    return "sql"


def _interpret_instruction(text: str) -> dict:
    """Deterministic stand-in for the orchestrator's relevance judgment: applies the
    instruction to every agent it was offered (AVAILABLE_AGENTS_JSON), so the fake backend
    can still exercise the full apply_pending_instructions -> agent prompt path in tests,
    not just always return applies_now=False the way the generic reflection fallback would."""
    instruction = extract_json("USER_INSTRUCTION_JSON", text) or {}
    agents = extract_json("AVAILABLE_AGENTS_JSON", text) or []
    target_agents = [a.get("agent") for a in agents if a.get("agent")]
    content = instruction.get("content")
    return {
        "applies_now": bool(target_agents),
        "target_agents": target_agents,
        "guidance_note": f"User note: {content}" if content else "",
    }


def _assistant_decision(text: str) -> dict:
    """Deterministic stand-in: picks the first offered agent, no clarification -- good
    enough to exercise the full assistant endpoint -> agent-run path in tests without
    depending on real LLM judgment calls."""
    agents = extract_json("AVAILABLE_AGENTS_JSON", text) or []
    if not agents:
        return {"needs_clarification": False, "chosen_agent": "", "action_note": ""}
    return {
        "needs_clarification": False, "chosen_agent": agents[0].get("agent", ""),
        "action_note": "Re-run requested via chat.", "options": [],
    }


def _qa_answer(text: str) -> dict:
    charts = extract_json("CHARTS_JSON", text) or []
    report = extract_json("REPORT_JSON", text) or []
    rows = extract_json("ROWS_JSON", text) or []
    chunks = extract_json("CHUNKS_JSON", text) or []
    diagnostic = extract_json("DIAGNOSTIC_TREE_JSON", text)

    text_low = text.lower()

    # Prioritize chart answer if charts exist and question asks about a chart
    if charts and any(k in text_low for k in ("chart", "graph", "plot", "visual")):
        title = charts[0].get("title", "Financial Chart")
        caption = charts[0].get("caption", "trend across reporting periods")
        return {
            "answer": f"The '{title}' visualization shows: {caption}.",
            "citations": [charts[0].get("chart_id", "chart_1")],
        }

    # Virtual CFO diagnostic reverse flow
    is_diagnostic_q = any(
        k in text_low for k in ("why", "cause", "investigat", "driver", "root cause", "management questions", "what changed", "reverse flow", "action point")
    )

    if diagnostic and (is_diagnostic_q or not (rows or report or chunks)):
        cname = diagnostic.get("canonical_name", "Metric")
        formula = diagnostic.get("formula", "")
        what_changed = diagnostic.get("what_changed", "")
        why = ", ".join(diagnostic.get("why_did_it_change", []))
        causes = [f"{rc.get('name')}: {rc.get('root_cause')}" for rc in diagnostic.get("what_caused_it", [])[:3]]
        causes_str = " | ".join(causes) if causes else "operational cost variances"
        inv = "; ".join(diagnostic.get("what_to_investigate", [])[:3])
        questions = "\n".join(f"- {q}" for q in diagnostic.get("what_to_ask_management", [])[:3])

        answer = (
            f"Virtual CFO Reverse-Flow Diagnostic for {cname}:\n"
            f"Formula: {formula}\n\n"
            f"1. What changed: {what_changed}\n"
            f"2. Why it changed (Governing components): {why}\n"
            f"3. What caused it (Root causes): {causes_str}\n"
            f"4. What to investigate: {inv}\n"
            f"5. What to ask management:\n{questions}"
        )
        return {"answer": answer, "citations": [diagnostic.get("metric_code", "virtual_cfo_compendium")]}
        caption = charts[0].get("caption", "trend across reporting periods")
        return {
            "answer": f"The '{title}' visualization shows: {caption}.",
            "citations": [charts[0].get("chart_id", "chart_1")],
        }
    if rows:
        preview = "; ".join(str(r) for r in rows[:3])
        return {"answer": f"Based on the ledger: {preview}.", "citations": [f"query_result:{i}" for i in range(len(rows[:3]))]}
    if chunks:
        preview = " ".join(str(c.get("text", ""))[:200] for c in chunks[:2])
        return {"answer": preview or "No matching content found.", "citations": [c.get("id", "") for c in chunks[:2]]}
    if report:
        title = report[0].get("title", "Report observation")
        body = report[0].get("body", "financial observations")
        return {"answer": f"Per the analysis report: {title} - {body}.", "citations": ["report_findings"]}
    return {"answer": "I could not find data to answer this question.", "citations": []}


def _generic_instance(schema: Type[T]) -> T:
    """Reflection-based fallback for any schema not special-cased above, so adding a new
    agent output type never crashes the fake gateway -- it just returns bland-but-valid data.
    """
    import typing

    def default_for(annotation):
        origin = typing.get_origin(annotation)
        if origin is typing.Union:
            args = [a for a in typing.get_args(annotation) if a is not type(None)]
            return default_for(args[0]) if args else None
        if origin in (list, typing.List):
            return []
        if origin in (dict, typing.Dict):
            return {}
        if origin is typing.Literal:
            args = typing.get_args(annotation)
            return args[0] if args else ""
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return {name: default_for(f.annotation) for name, f in annotation.model_fields.items()}
        if annotation is str:
            return ""
        if annotation is int:
            return 0
        if annotation is float:
            return 0.0
        if annotation is bool:
            return False
        return None

    data = {name: default_for(f.annotation) for name, f in schema.model_fields.items()}
    return schema.model_validate(data)
