import type { JobStatus } from "./types";

export type Stage = "data" | "analysis" | "delivery";

export interface AgentDef {
  id: string;
  label: string;
  does: string;
  stage: Stage;
}

const DATA: AgentDef[] = [
  { id: "intake_classifier", label: "Intake", does: "Identifies each document's statement type and period", stage: "data" },
  { id: "extractor", label: "Extraction", does: "Parses tables out of CSV, Excel, PDF and Images via OCR", stage: "data" },
  { id: "schema_mapper", label: "Account mapping", does: "Maps line items to the chart of accounts", stage: "data" },
  { id: "reconciler", label: "Reconciliation", does: "Checks the statements tie out", stage: "data" },
];

const ANALYSIS: Record<string, AgentDef> = {
  ratio: { id: "ratio", label: "Ratios & trends", does: "Computes liquidity, leverage and margin ratios", stage: "analysis" },
  cash_wc: { id: "cash_wc", label: "Cash & working capital", does: "Receivable, inventory and payable cycles", stage: "analysis" },
  forecast: { id: "forecast", label: "Forecast", does: "Projects the next periods", stage: "analysis" },
  risk: { id: "risk", label: "Risk & anomalies", does: "Flags unusual movements and risk signals", stage: "analysis" },
  gst: { id: "gst", label: "GST compliance", does: "Reconciles GSTR filings against the books", stage: "analysis" },
  detailed_analytics: {
    id: "detailed_analytics", label: "Statement analysis", stage: "analysis",
    does: "Year-on-year and common-size statements, DuPont, growth and the profit bridge",
  },
};

const DELIVERY: AgentDef[] = [
  { id: "insight_reasoner", label: "Insights", does: "Synthesises findings into conclusions", stage: "delivery" },
  { id: "chart_spec", label: "Charts", does: "Builds the report's visualisations", stage: "delivery" },
  { id: "report_writer", label: "Report drafting", does: "Writes the executive report", stage: "delivery" },
  { id: "verifier", label: "Verification", does: "Checks every figure against the ledger", stage: "delivery" },
];

export const ORCHESTRATOR: AgentDef = {
  id: "orchestrator", label: "Your guidance", does: "Relays your notes to the relevant agents", stage: "data",
};

export const TEMPLATES: Record<string, { label: string; blurb: string; modules: string[] }> = {
  full_analysis: {
    label: "Full financial analysis",
    blurb: "Ratios, working capital, forecast, risk, GST and a full statement analysis.",
    modules: ["ratio", "cash_wc", "forecast", "risk", "gst", "detailed_analytics"],
  },
  lender_credit_memo: {
    label: "Lender credit memo",
    blurb: "Coverage, leverage and cash-flow focus for a credit decision.",
    modules: ["ratio", "cash_wc", "risk", "forecast", "detailed_analytics"],
  },
  bank_statement_review: {
    label: "Bank statement review",
    blurb: "Cash movements, payer concentration and anomalies from bank statements.",
    modules: ["cash_wc", "risk", "detailed_analytics"],
  },
  gst_reconciliation: {
    label: "GST reconciliation",
    blurb: "GSTR-3B and 2B against the books.",
    modules: ["gst"],
  },
};

export function agentsFor(template: string): AgentDef[] {
  const modules = (TEMPLATES[template] ?? TEMPLATES.full_analysis).modules;
  return [...DATA, ...modules.map((m) => ANALYSIS[m]), ...DELIVERY];
}

const ALL = [...DATA, ...Object.values(ANALYSIS), ...DELIVERY, ORCHESTRATOR];

/** Agents the backend registry knows about that this file doesn't (GET /api/agents), so a newly
 * added agent is labelled and placed in the right stage without a frontend change. */
const REGISTERED = new Map<string, AgentDef>();
export function registerAgents(list: { name: string; label: string; description: string; stage: string }[]) {
  for (const a of list) {
    if (ALL.some((x) => x.id === a.name)) continue;
    const stage = (["data", "analysis", "delivery"].includes(a.stage) ? a.stage : "delivery") as Stage;
    REGISTERED.set(a.name, { id: a.name, label: a.label, does: a.description, stage });
  }
}

export function agentDef(id: string): AgentDef {
  return ALL.find((a) => a.id === id) ?? REGISTERED.get(id)
    ?? { id, label: id.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()), does: "", stage: "delivery" };
}

export const STAGE_LABEL: Record<Stage, string> = {
  data: "Prepare the data",
  analysis: "Analyse",
  delivery: "Write the report",
};

/** Statuses where the pipeline is actively working (chat steers the run instead of asking Q&A). */
export const ACTIVE_STATUSES = new Set<JobStatus>([
  "CREATED", "INGESTING", "MAPPING", "RECONCILING", "DATA_VALIDATED", "ANALYZING",
  "SYNTHESIZING", "VERIFYING", "RENDERING",
]);

export function isActive(status: JobStatus | undefined): boolean {
  return !!status && ACTIVE_STATUSES.has(status);
}

export type Tone = "neutral" | "running" | "success" | "attention" | "danger";

export function statusInfo(status: JobStatus | undefined): { label: string; tone: Tone } {
  switch (status) {
    case undefined: return { label: "Loading", tone: "neutral" };
    case "COMPLETED": return { label: "Complete", tone: "success" };
    case "FAILED": return { label: "Failed", tone: "danger" };
    case "AWAITING_REVIEW": return { label: "Needs your review", tone: "attention" };
    case "NEEDS_ANALYST": return { label: "Needs an analyst", tone: "attention" };
    case "PARTIAL": return { label: "Partially complete", tone: "attention" };
    case "CREATED": return { label: "Queued", tone: "running" };
    case "INGESTING": return { label: "Reading documents", tone: "running" };
    case "MAPPING": return { label: "Mapping accounts", tone: "running" };
    case "RECONCILING": return { label: "Reconciling", tone: "running" };
    case "DATA_VALIDATED": return { label: "Data validated", tone: "running" };
    case "ANALYZING": return { label: "Analysing", tone: "running" };
    case "SYNTHESIZING": return { label: "Drawing conclusions", tone: "running" };
    case "VERIFYING": return { label: "Verifying figures", tone: "running" };
    case "RENDERING": return { label: "Rendering report", tone: "running" };
    default: return { label: status, tone: "neutral" };
  }
}
