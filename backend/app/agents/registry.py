"""Agent registry: the single source of truth for which agents exist, which stage they run
in, what they depend on, and how they're described to the orchestrator LLM and the UI.

Before this, the same knowledge lived in four places that drifted independently -- the
orchestrator's STAGE_AGENT_DESCRIPTIONS prompt table, the assistant endpoint's own map of
re-runnable delivery agents, the delivery supervisor's hard-coded sequence, and the
frontend's AGENT_META/agentToStage tables. Adding an agent now means adding one
AgentDescriptor here; the orchestrator, the chat assistant, the delivery DAG and the web UI
(via GET /api/agents) all read it.

Classes are referenced by import path and loaded lazily, so this module stays import-cycle
free (agents import tools, tools import nothing from here).
"""
from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass, field

STAGES = ("data", "analysis", "delivery")


@dataclass(frozen=True)
class AgentDescriptor:
    name: str
    stage: str
    label: str
    icon: str
    description: str  # plain language, shown to the orchestrator LLM when routing instructions
    class_path: str | None = None  # "module:Class"; None for pseudo-agents (orchestrator)
    depends_on: tuple[str, ...] = field(default_factory=tuple)  # within-stage DAG edges
    steerable: bool = False  # can receive mid-run user guidance from the orchestrator
    rerunnable: bool = False  # can be re-run on demand from the chat assistant

    def load(self):
        if not self.class_path:
            raise LookupError(f"agent '{self.name}' has no implementation class")
        module_name, cls_name = self.class_path.split(":")
        return getattr(importlib.import_module(module_name), cls_name)

    def to_public_dict(self) -> dict:
        data = asdict(self)
        data.pop("class_path")
        data["depends_on"] = list(self.depends_on)
        return data


AGENTS: tuple[AgentDescriptor, ...] = (
    # --- data stage (per-document fan-out, then one reconciliation pass) ---
    AgentDescriptor("intake_classifier", "data", "Intake", "🗂️", "classifies each uploaded document and its reporting period",
                    "app.agents.data.intake:IntakeAgent"),
    AgentDescriptor("extractor", "data", "Extractor", "📐", "detects table boundaries and extracts every sheet/table",
                    "app.agents.data.extractor:ExtractorAgent", depends_on=("intake_classifier",)),
    AgentDescriptor("schema_mapper", "data", "Schema Mapper", "🔗",
                    "maps raw financial-statement row labels to canonical chart-of-accounts ids",
                    "app.agents.data.mapper:SchemaMapperAgent", depends_on=("extractor",), steerable=True),
    AgentDescriptor("reconciler", "data", "Reconciler", "✅", "runs cross-statement reconciliation checks",
                    "app.agents.data.reconciler:ReconcilerAgent", depends_on=("schema_mapper",)),
    AgentDescriptor("verification_advisor", "data", "Verification Advisor", "🛡️",
                    "analyzes verification review items, provides CoA recommendations and auto-resolves discrepancies",
                    "app.agents.data.verification_advisor:VerificationAdvisorAgent", depends_on=("reconciler",), steerable=True, rerunnable=True),
    # --- analysis stage (independent modules, run in parallel) ---
    AgentDescriptor("ratio", "analysis", "Ratio & Trend", "📊",
                    "computes profitability/liquidity/leverage/efficiency ratios and writes trend findings",
                    "app.agents.analysis.ratio:RatioTrendAgent", steerable=True, rerunnable=True),
    AgentDescriptor("cash_wc", "analysis", "Cash & Working Capital", "💵",
                    "computes cash flow and working capital metrics and findings",
                    "app.agents.analysis.cash_wc:CashWorkingCapitalAgent", steerable=True, rerunnable=True),
    AgentDescriptor("forecast", "analysis", "Forecast", "🔮", "projects future revenue/PAT and writes forecast findings",
                    "app.agents.analysis.forecast:ForecastAgent", steerable=True, rerunnable=True),
    AgentDescriptor("risk", "analysis", "Risk & Anomaly", "⚠️", "flags anomalies/red flags and computes the overall risk score",
                    "app.agents.analysis.risk:RiskAnomalyAgent", steerable=True, rerunnable=True),
    AgentDescriptor("gst", "analysis", "GST Compliance", "🧾", "reconciles GST returns against the ledger",
                    "app.agents.analysis.gst:GstComplianceAgent", steerable=True, rerunnable=True),
    AgentDescriptor("detailed_analytics", "analysis", "Detailed Analytics", "🧮",
                    "builds the detailed statement analysis: horizontal/YoY and common-size analysis, DuPont "
                    "decomposition, CAGR, profit bridge, net debt and bank cash-flow analytics",
                    "app.agents.analysis.detailed_analytics:DetailedAnalyticsAgent", steerable=True, rerunnable=True),
    # --- delivery stage (a real DAG, see DeliverySupervisor) ---
    AgentDescriptor("insight_reasoner", "delivery", "Insight Reasoner", "💡",
                    "synthesizes findings across all analysis modules into ranked insights and computes health score",
                    "app.agents.delivery.insight:InsightReasonerAgent", steerable=True, rerunnable=True),
    AgentDescriptor("chart_spec", "delivery", "Chart Builder", "📈",
                    "selects and renders financial trend charts, profit bridge and cost structure visualizations",
                    "app.agents.delivery.chart_spec:ChartSpecAgent", steerable=True, rerunnable=True),
    AgentDescriptor("report_writer", "delivery", "Report Writer", "✍️", "drafts the executive financial analysis report and narrative",
                    "app.agents.delivery.report_writer:ReportWriterAgent",
                    depends_on=("insight_reasoner", "chart_spec"), steerable=True, rerunnable=True),
    AgentDescriptor("verifier", "delivery", "Verifier", "🔍", "checks every figure and claim in the draft against the data",
                    "app.agents.verifier:VerifierAgent", depends_on=("report_writer",)),
    # --- pseudo-agent: shows up in the task trace when it relays user guidance ---
    AgentDescriptor("orchestrator", "orchestration", "Orchestrator", "🧭", "relays your notes to the relevant agent(s)"),
)

_BY_NAME = {a.name: a for a in AGENTS}


def get(name: str) -> AgentDescriptor:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise LookupError(f"unknown agent '{name}'") from None


def for_stage(stage: str) -> list[AgentDescriptor]:
    return [a for a in AGENTS if a.stage == stage]


def steerable_descriptions(stage: str) -> dict[str, str]:
    """{agent_name: description} for the agents in `stage` that accept mid-run guidance --
    what the orchestrator LLM is allowed to route a user's instruction to."""
    return {a.name: a.description for a in for_stage(stage) if a.steerable}


def rerunnable(stage: str | None = None) -> list[AgentDescriptor]:
    return [a for a in AGENTS if a.rerunnable and (stage is None or a.stage == stage)]
