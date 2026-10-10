"""Deterministic stand-in for a real LLM, used when LLM_BACKEND=fake (the default until a
real custom endpoint is wired up). It does not "understand" text -- it pattern-matches on
keywords and on the tagged JSON blobs agents embed via prompt_utils.embed_json, so the
rest of the system (tool calls, reconciliation, metrics, report binding) can be built and
tested end-to-end before real credentials exist. See app/agents/schemas.py for the shapes
it fills in.
"""
from __future__ import annotations

import re
from typing import Type, TypeVar

from pydantic import BaseModel

from app.agents import schemas as sch
from app.domain.coa import lookup_synonym
from app.llm_gateway.base import LLMGateway
from app.llm_gateway.prompt_utils import all_message_text, extract_json, last_user_text

T = TypeVar("T", bound=BaseModel)


class FakeLLMGateway(LLMGateway):
    def complete(self, messages, schema: Type[T] | None = None, tier: str = "default", max_retries: int = 1,
                 max_tokens: int | None = None):
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
        account_id = lookup_synonym(label.split("  [section:", 1)[0])
        if account_id:
            out.append({"source_label": label, "account_id": account_id, "confidence": 0.9})
        else:
            out.append({"source_label": label, "account_id": "UNMAPPED", "confidence": 0.3})
    return out


_MONTHLY_BANK = {"bank_inflows", "bank_outflows", "bank_net_flow"}


def _bank_rule_findings(by_code: dict[str, list[dict]]) -> list[dict]:
    """Threshold findings on the statement-level bank metrics (calc/bank_metrics.py), phrased
    the way a credit analyst would flag them. Values are only compared, never printed."""
    def latest(code):
        points = by_code.get(code)
        return sorted(points, key=lambda p: p["period_end"])[-1] if points else None

    out = []
    cover, payer = latest("bank_cash_cover_months"), latest("bank_top_payer_share")
    low, neg = latest("bank_min_balance"), latest("bank_negative_month_share")
    def ref(code: str, m: dict) -> str:
        return "{{m:" + code + ":" + m["period_end"] + "}}"

    if cover and cover.get("value") is not None:
        thin = cover["value"] < 1.0
        out.append({"title": "Cash cover is thin" if thin else "Cash cover is comfortable",
                    "body": f"The closing balance covers {ref('bank_cash_cover_months', cover)} of typical monthly outflows"
                            + ("; a single slow month could strain payments." if thin else "."),
                    "severity": "warn" if thin else "info", "metric_ids": [cover.get("id", "")]})
    if payer and payer.get("value") is not None and payer["value"] > 0.4:
        out.append({"title": "Receipts depend heavily on one payer",
                    "body": f"The largest payer accounts for {ref('bank_top_payer_share', payer)} of all money received. Losing or delaying "
                            f"that customer would hit cash flow directly; check contract terms and ageing.",
                    "severity": "warn" if payer["value"] > 0.5 else "info", "metric_ids": [payer.get("id", "")]})
    if low and low.get("value") is not None and low["value"] < 0:
        out.append({"title": "The account went overdrawn",
                    "body": f"The balance fell to {ref('bank_min_balance', low)} at its lowest point in the statement period.",
                    "severity": "error", "metric_ids": [low.get("id", "")]})
    if neg and neg.get("value") is not None and neg["value"] >= 0.5:
        out.append({"title": "Outflows beat inflows in most months",
                    "body": f"{ref('bank_negative_month_share', neg)} of months were cash-negative across the statement period.",
                    "severity": "warn", "metric_ids": [neg.get("id", "")]})
    return out


def _generic_findings(text: str) -> list[dict]:
    """Deterministic stand-in for an analysis module's findings: reports the largest
    period-on-period moves (favourable or not) using {{m:code:period}} bindings only, the
    same contract the real prompt (prompts.ANALYSIS_MODULE) imposes -- never raw numbers."""
    from app.domain.metric_facts import LABELS, LOWER_IS_BETTER

    metrics = extract_json("METRICS_JSON", text) or []
    by_code: dict[str, list[dict]] = {}
    for m in metrics:
        code = m.get("metric_code") or m.get("code")
        # Month-to-month swings in bank flows are noise; the statement-level summaries carry the signal.
        if code and m.get("period_end") and code not in _MONTHLY_BANK:
            by_code.setdefault(code, []).append(m)

    findings = _bank_rule_findings(by_code)

    moves = []
    for code, points in by_code.items():
        points = sorted(points, key=lambda p: p["period_end"])
        cur, prev = points[-1], points[-2] if len(points) > 1 else None
        if prev is None or cur.get("value") is None or prev.get("value") in (None, 0):
            continue
        rel = (cur["value"] - prev["value"]) / abs(prev["value"])
        moves.append((abs(rel), rel, code, cur, prev))
    moves.sort(reverse=True)

    for magnitude, rel, code, cur, prev in moves[:4]:
        if magnitude < 0.02:
            continue
        name = LABELS.get(code, code.replace("_", " "))
        favourable = (rel < 0) if code in LOWER_IS_BETTER else (rel > 0)
        verb = ("improved" if favourable else "deteriorated") if code not in LOWER_IS_BETTER else \
               ("fell" if rel < 0 else "rose")
        findings.append({
            "title": f"{name} {verb}",
            "body": (f"{name} moved to {{{{m:{code}:{cur['period_end']}}}}} from "
                     f"{{{{m:{code}:{prev['period_end']}}}}}"
                     + ("." if favourable else "; understand the driver before relying on the trend.")),
            "severity": "info" if favourable or magnitude < 0.1 else "warn",
            "metric_ids": [cur.get("id", code), prev.get("id", code)],
        })
    if not findings:
        for code, points in list(by_code.items())[:2]:
            cur = sorted(points, key=lambda p: p["period_end"])[-1]
            name = LABELS.get(code, code.replace("_", " "))
            findings.append({
                "title": f"{name} for the latest period",
                "body": f"{name} stands at {{{{m:{code}:{cur['period_end']}}}}}; there is no earlier period to compare against.",
                "severity": "info", "metric_ids": [cur.get("id", code)],
            })
    return findings


def _insights_from_metrics(text: str) -> list[dict]:
    metrics = extract_json("METRICS_JSON", text) or []
    ds_profile = extract_json("DATASET_PROFILE_JSON", text) or {}
    insights = []

    # First: extract insights from dynamic dataset profile attributes (if present)
    if ds_profile and ds_profile.get("datasets"):
        for ds in ds_profile.get("datasets", []):
            name = ds.get("name", "Dataset")
            top_drivers = ds.get("top_drivers", {})
            measure_totals = ds.get("measure_totals", {})

            for dim, d_info in top_drivers.items():
                top_names = d_info.get("top_names", [])
                share_pct = d_info.get("share_pct", 0)
                if top_names:
                    insights.append({
                        "title": f"Concentration in {dim} ({share_pct}%)",
                        "body": f"In {name}, the top {dim.lower()}s ({', '.join(top_names)}) drive {share_pct}% of total activity.",
                        "metric_ids": [],
                        "recommendation": f"Monitor operational dependence and credit terms across dominant {dim.lower()}s.",
                    })
            for m, t_info in list(measure_totals.items())[:2]:
                insights.append({
                    "title": f"{m} Volume Profile",
                    "body": f"Total {m} stands at {t_info.get('sum', 0):,} across {ds.get('row_count', 0)} entries (average {t_info.get('avg', 0):,}).",
                    "metric_ids": [],
                    "recommendation": f"Track {m.lower()} velocity and margin consistency over operational cycles.",
                })

    if not metrics:
        return insights or [{
            "title": "Financial Data Overview",
            "body": "Analysis completed across the validated financial statements.",
            "metric_ids": [],
            "recommendation": "Review uploaded statements for further operational details.",
        }]

    # Group metrics by code with valid numeric values
    by_code: dict[str, list[dict]] = {}
    for m in metrics:
        code = m.get("metric_code") or m.get("code")
        if code and m.get("value") is not None:
            by_code.setdefault(code, []).append(m)

    priority_codes = [
        "revenue", "gross_profit", "gross_profit_pct", "ebitda", "ebitda_margin",
        "operating_margin", "net_income", "current_ratio", "quick_ratio",
        "debt_to_equity", "interest_coverage", "fcf", "cfo", "health_score"
    ]
    ordered_codes = [c for c in priority_codes if c in by_code]
    for c in by_code:
        if c not in ordered_codes:
            ordered_codes.append(c)

    for code in ordered_codes[:7]:
        pts = sorted(by_code[code], key=lambda x: str(x.get("period_end") or x.get("period") or ""))
        cur = pts[-1]
        cur_period = cur.get("period_end") or cur.get("period") or ""
        cur_id = cur.get("id", code)
        code_name = code.replace("_", " ").title()

        if len(pts) >= 2:
            prev = pts[-2]
            prev_period = prev.get("period_end") or prev.get("period") or ""
            prev_id = prev.get("id", code)
            val_cur = float(cur["value"])
            val_prev = float(prev["value"])
            diff = val_cur - val_prev

            if diff > 0:
                verb = "expanded" if "margin" in code or "pct" in code else "grew"
                body = f"{code_name} {verb} to {{{{m:{code}:{cur_period}}}}} from {{{{m:{code}:{prev_period}}}}}."
            elif diff < 0:
                verb = "contracted" if "margin" in code or "pct" in code else "declined"
                body = f"{code_name} {verb} to {{{{m:{code}:{cur_period}}}}} from {{{{m:{code}:{prev_period}}}}}."
            else:
                body = f"{code_name} held steady at {{{{m:{code}:{cur_period}}}}} compared to {{{{m:{code}:{prev_period}}}}}."
            rec = f"Continue tracking {code.replace('_', ' ')} trajectory against benchmarks."
            metric_ids = [cur_id, prev_id]
        else:
            body = f"{code_name} stands at {{{{m:{code}:{cur_period}}}}} for the current reporting period."
            rec = f"Establish multi-period baseline for {code.replace('_', ' ')}."
            metric_ids = [cur_id]

        insights.append({
            "title": f"{code_name} Performance",
            "body": body,
            "metric_ids": metric_ids,
            "recommendation": rec,
        })

    return insights or [{
        "title": "Financial Metrics Overview",
        "body": "Operational indicators compiled successfully.",
        "metric_ids": [],
        "recommendation": None,
    }]


def _chart_captions(text: str) -> list[dict]:
    charts = extract_json("CHARTS_JSON", text) or []
    return [
        {"chart_id": c.get("chart_id", ""),
         "caption": (c.get("computed_takeaway") or f"{c.get('title', 'This chart')} over the periods shown.")}
        for c in charts if c.get("chart_id")
    ]


def _report_draft(text: str) -> dict:
    skeleton = extract_json("SKELETON_JSON", text) or []
    insights = extract_json("INSIGHTS_JSON", text) or []
    charts = extract_json("CHARTS_JSON", text) or []
    ds_profile = extract_json("DATASET_PROFILE_JSON", text) or {}
    chart_ids = [c.get("chart_id") for c in charts if c.get("chart_id")]

    if skeleton:
        sections = []
        for i, sk in enumerate(skeleton):
            s_key = sk.get("section_key")
            ins_body = insights[i].get("body", "") if i < len(insights) else ""
            guide = sk.get("diagnostic_guide") or []

            if s_key == "dataset_attributes" and ds_profile.get("datasets"):
                lines = []
                for ds in ds_profile["datasets"]:
                    d_str = ", ".join(ds.get("dimensions", [])) or "None"
                    m_str = ", ".join(ds.get("measures", [])) or "None"
                    lines.append(
                        f"Dataset '{ds.get('name')}' comprises {ds.get('row_count')} records with dimensions ({d_str}) "
                        f"and quantitative measures ({m_str})."
                    )
                body_text = " ".join(lines) + " The multiagent pipeline analyzed these dimensional attributes first to build tailored visualizations and driver rankings."
            elif s_key == "operational_drivers" and ds_profile.get("datasets"):
                lines = []
                for ds in ds_profile["datasets"]:
                    for dim, d_info in ds.get("top_drivers", {}).items():
                        lines.append(
                            f"Within dimension '{dim}', top contributors ({', '.join(d_info.get('top_names', []))}) "
                            f"command {d_info.get('share_pct')}% of aggregate volume."
                        )
                body_text = " ".join(lines) or "Detailed distribution and Pareto concentrations across primary operational dimensions."
            elif guide and not ins_body:
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
    from app.domain.chat_intent import hinted_agent

    agents = extract_json("AVAILABLE_AGENTS_JSON", text) or []
    if not agents:
        return {"needs_clarification": False, "chosen_agent": "", "action_note": ""}
    message = (extract_json("USER_MESSAGE_JSON", text) or {}).get("message", "")
    names = [a.get("agent", "") for a in agents]
    chosen = hinted_agent(message, names) or names[0]
    return {
        "needs_clarification": False, "chosen_agent": chosen,
        "action_note": message or "Re-run requested via chat.", "options": [],
    }


def _period_label(iso: str) -> str:
    """'2024-03-31' -> 'FY24' (Indian fiscal year end); other dates -> 'Jan 2024'."""
    import calendar
    from datetime import date

    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    if d.month == 3 and d.day == 31:
        return f"FY{str(d.year)[2:]}"
    return f"{calendar.month_abbr[d.month]} {d.year}"


_ACRONYMS = ("COGS", "SG&A", "D&A", "EBITDA", "EBIT", "PAT", "PBT", "GST", "ITC", "OCF", "CAPEX", "R&D", "ROE", "ROCE")


def _sentence_case(text: str) -> str:
    """The diagnostic knowledge base writes component names partly in capitals ("GROSS MARGIN
    DRIVERS (Revenue & COGS)"); lower-case the shouted words but keep real acronyms."""
    if not text:
        return text

    def fix(match: re.Match) -> str:
        word = match.group(0)
        return word if word in _ACRONYMS or len(word) <= 2 else word.lower()

    out = re.sub(r"[A-Z][A-Z&-]+", fix, text)
    return out[:1].upper() + out[1:]


def _fact_sentence(f: dict) -> str:
    line = f"**{f['metric']}** is {f['display']} for {_period_label(f['period'])}"
    if f.get("prior_display"):
        moved = {"up": "up from", "down": "down from", "flat": "unchanged from"}[f.get("direction", "flat")]
        line += f", {moved} {f['prior_display']} in {_period_label(f['prior_period'])}"
        if f.get("direction") != "flat":
            line += f" ({f['change_display']})"
        if f.get("improved") is True:
            line += ", a favourable move"
        elif f.get("improved") is False:
            line += ", an unfavourable move"
    return line + "."


def _qa_answer(text: str) -> dict:
    """Deterministic stand-in for the QA composer, following the same rules the real prompt
    gives the model (prompts.QA_COMPOSER): lead with the verified figures in FACTS_JSON,
    then the diagnostic drill-down for "why" questions, then what the analysis flagged."""
    facts = extract_json("FACTS_JSON", text) or []
    charts = extract_json("CHARTS_JSON", text) or []
    report = extract_json("REPORT_JSON", text) or []
    rows = extract_json("ROWS_JSON", text) or []
    chunks = extract_json("CHUNKS_JSON", text) or []
    diagnostic = extract_json("DIAGNOSTIC_TREE_JSON", text)
    import re

    match = re.search(r"^Question:(.*)$", text, re.MULTILINE)
    question = match.group(1).strip() if match else ""
    q_low = question.lower()

    if charts and any(k in q_low for k in ("chart", "graph", "plot", "visual")):
        lines = [f"- **{c.get('title', 'Chart')}**: {c.get('caption') or 'trend across the reporting periods'}"
                 for c in charts[:4]]
        return {"answer": "Here is what the charts show:\n\n" + "\n".join(lines),
                "citations": [c.get("chart_id", "") for c in charts[:4]]}

    parts: list[str] = []
    citations: list[str] = []

    is_why = any(k in q_low for k in ("why", "cause", "driver", "explain", "what changed", "reason", "investigat",
                                      "ask management"))
    if diagnostic and (is_why or not facts):
        # The Virtual CFO five-point reverse flow, with step 1 anchored in the actual figures.
        name = diagnostic.get("canonical_name", "this metric")
        components = [_sentence_case(c) for c in (diagnostic.get("why_did_it_change") or [])]
        causes = [f"{rc.get('name')}: {rc.get('root_cause')}" for rc in (diagnostic.get("what_caused_it") or [])[:3]]
        checks = (diagnostic.get("what_to_investigate") or [])[:3]
        asks = (diagnostic.get("what_to_ask_management") or [])[:3]
        changed = " ".join(_fact_sentence(f) for f in facts[:2]) or diagnostic.get("what_changed", "")
        if diagnostic.get("formula"):
            changed += f" It is calculated as {diagnostic['formula']}."
        steps = [f"**Virtual CFO diagnostic: {name}**", f"**1. What changed**\n{changed.strip()}"]
        steps.append("**2. Why it changed**\n" + (", ".join(components[:4]) + "." if components
                                                   else "The governing components are not broken out in this data."))
        steps.append("**3. What caused it**\n" + ("\n".join(f"- {c}" for c in causes) if causes
                                                   else "- No specific root cause can be isolated from the statements."))
        steps.append("**4. What to investigate**\n" + "\n".join(f"- {c}" for c in checks))
        steps.append("**5. What to ask management**\n" + "\n".join(f"- {q}" for q in asks))
        parts.append("\n\n".join(steps))
        citations += [f["metric_code"] for f in facts[:2]] + [diagnostic.get("metric_code", "virtual_cfo_compendium")]
    elif facts:
        shown = facts[:5]
        parts.append("\n".join(f"- {_fact_sentence(f)}" for f in shown) if len(shown) > 1 else _fact_sentence(shown[0]))
        moved = [f for f in shown if f.get("improved") is not None]
        if len(moved) > 1:
            worse = sum(1 for f in moved if f["improved"] is False)
            verdict = ("all moved favourably" if worse == 0 else "all moved unfavourably" if worse == len(moved)
                       else f"{worse} of {len(moved)} moved unfavourably, so the picture is mixed")
            parts.append(f"**On balance:** of the measures that changed, {verdict}.")
        citations += [f["metric_code"] for f in shown]

    if report:
        rank = {"error": 0, "warn": 1, "info": 2}
        flagged = sorted(report, key=lambda r: rank.get(r.get("severity"), 3))[:4]
        label = {"error": "Critical", "warn": "Watch", "info": "Note"}
        lines = [f"- **{label.get(r.get('severity'), 'Note')}: {r.get('title', 'Finding')}.** {r.get('body') or ''}".rstrip()
                 for r in flagged]
        parts.append("**What the analysis flagged**\n" + "\n".join(lines))
        citations.append("report_findings")

    if not parts and rows:
        lines = [f"- {r.get('metric_code', 'value')} ({r.get('period_end', '')}): {r.get('value')}" for r in rows[:6]]
        parts.append("From the computed metrics:\n" + "\n".join(lines))
        citations += [f"query_result:{i}" for i in range(min(len(rows), 6))]
    if not parts and chunks:
        parts.append(" ".join(str(c.get("text", ""))[:300] for c in chunks[:2]))
        citations += [c.get("id", "") for c in chunks[:2]]

    if not parts:
        return {"answer": ("I couldn't find figures in this analysis that answer that. I can answer questions about "
                           "specific ratios (for example margins, liquidity, leverage, working capital or cash), explain "
                           "why a ratio moved, summarise the risks the analysis flagged, or re-run a module with new "
                           "assumptions."), "citations": []}
    return {"answer": "\n\n".join(parts), "citations": citations}


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
