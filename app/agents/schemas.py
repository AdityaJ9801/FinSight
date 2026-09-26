"""Structured-output schemas shared by agents and the LLM gateway (real + fake).

Kept in one module (no dependency on llm_gateway or on any single agent) so both the real
HTTP client and the fake/deterministic client can validate against, and pattern-match on,
the same set of types without import cycles.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClassificationResult(BaseModel):
    # reasoning comes first so the model has to work through the excerpt (which may open
    # with several metadata lines before anything statement-like) before committing to a
    # doc_type, rather than pattern-matching the first line and stopping there.
    reasoning: str | None = None
    doc_type: str  # one of app.models.document.DOC_TYPES
    period_start: str | None = None  # ISO date, best guess
    period_end: str | None = None
    unit_scale: float = 1
    currency: str = "INR"
    confidence: float = 0.5


class TableBoundaryResult(BaseModel):
    """Where the real column-header row is, when the deterministic heuristic
    (tools/table_detect.py) can't find a confident candidate -- e.g. because the metadata
    block above the table is itself table-shaped enough to confuse a pure heuristic."""
    reasoning: str  # required: think through what each row is before answering, not after
    header_row_idx: int  # 0-indexed row number of the actual column-header/period row
    confidence: float = 0.5


class MappingItem(BaseModel):
    source_label: str
    account_id: str
    confidence: float = 0.5


class MappingSet(BaseModel):
    mappings: list[MappingItem] = Field(default_factory=list)


class ExplanationResult(BaseModel):
    explanation: str
    likely_cause: str | None = None


class FindingItem(BaseModel):
    title: str
    body: str
    severity: Literal["info", "warn", "error"] = "info"
    metric_ids: list[str] = Field(default_factory=list)


class FindingsSet(BaseModel):
    findings: list[FindingItem] = Field(default_factory=list)


class InsightItem(BaseModel):
    title: str
    body: str  # may reference {{m:code:period}} placeholders, never raw numbers
    metric_ids: list[str] = Field(default_factory=list)
    recommendation: str | None = None


class InsightSet(BaseModel):
    insights: list[InsightItem] = Field(default_factory=list)


class ChartCaptionItem(BaseModel):
    chart_id: str  # matched back to the chart it explains; not trusted for anything else
    caption: str  # 2-3 sentences on what the chart shows and why it matters, grounded in its own data points


class ChartCaptionSet(BaseModel):
    captions: list[ChartCaptionItem] = Field(default_factory=list)


class ReportSection(BaseModel):
    heading: str
    body: str  # placeholders only for numbers: {{m:metric_code:period_end}}
    section_key: str | None = None
    kind: str = "narrative"  # narrative | kpi_summary | data_quality | data_diagnostic
    chart_ids: list[str] = Field(default_factory=list)


class ReportDraftResult(BaseModel):
    title: str
    sections: list[ReportSection] = Field(default_factory=list)


class VerifierVerdict(BaseModel):
    passed: bool
    claim_feedback: list[str] = Field(default_factory=list)


class RouteDecision(BaseModel):
    reasoning: str | None = None
    route: Literal["sql", "document_rag", "report_lookup", "chart_lookup", "action_request", "out_of_scope"]


class QAAnswerResult(BaseModel):
    answer: str
    citations: list[str] = Field(default_factory=list)


class InstructionInterpretation(BaseModel):
    """The orchestrator's read on whether a user's mid-run instruction applies to the
    stage about to execute, and if so, what to relay to which of that stage's agents."""
    reasoning: str | None = None
    applies_now: bool
    target_agents: list[str] = Field(default_factory=list)
    guidance_note: str = ""


class AssistantOption(BaseModel):
    label: str
    description: str
    agent: str  # must be one of the names given in AVAILABLE_AGENTS_JSON


class AssistantDecision(BaseModel):
    """The orchestrator's read on a post-hoc chat request: does it need a specific
    analysis agent re-run, and if the request is genuinely ambiguous between more than one
    agent/interpretation, what are the concrete options to offer the user (Claude-Code-
    style multiple choice) instead of guessing."""
    reasoning: str | None = None
    needs_clarification: bool
    question: str = ""
    options: list[AssistantOption] = Field(default_factory=list)
    chosen_agent: str = ""  # set when needs_clarification is False
    action_note: str = ""  # what to tell chosen_agent to focus on, from the user's own words
