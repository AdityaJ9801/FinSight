export type JobStatus =
  | "CREATED" | "INGESTING" | "MAPPING" | "RECONCILING" | "AWAITING_REVIEW" | "DATA_VALIDATED"
  | "ANALYZING" | "PARTIAL" | "SYNTHESIZING" | "VERIFYING" | "NEEDS_ANALYST" | "RENDERING"
  | "COMPLETED" | "FAILED";

export interface Job {
  id: string;
  stage: string;
  status: JobStatus;
  progress_pct: number;
  progress_message: string;
  dataset_version_id: string | null;
  error: string | null;
  updated_at: string;
  created_at: string | null;
  goal: string;
  plan_template: string;
  company_name: string | null;
  industry: string | null;
  dataset_versions?: number;
  run_started_at?: string | null;
  document_count?: number;
  documents?: JobDocument[];
}

export interface JobDocument {
  id: string;
  filename: string;
  doc_type: string | null;
  status: string;
  period_end: string | null;
}

export interface TaskRun {
  id: string;
  agent: string;
  status: "done" | "partial" | "failed" | "needs_review" | string;
  summary: string | null;
  confidence: number | null;
  issues: { severity?: string; code?: string; message?: string }[] | null;
  created_at: string;
}

export interface Metric {
  id: string;
  metric_code: string;
  period_end: string;
  value: number | null;
  unit: string;
}

export interface Finding {
  id: string;
  module: string;
  severity: "info" | "warn" | "error" | string;
  title: string;
  body: string | null;
  metric_ids: string[] | null;
  confidence: number | null;
}

export interface Chart {
  chart_id: string;
  title: string;
  caption: string;
  png_base64: string;
  /** One-line computed "so what" printed under the chart title (deterministic, not the model). */
  takeaway?: string;
  section_key?: string | null;
}

export interface ValidationCheck {
  check_code: string;
  status: string;
  expected: number | null;
  actual: number | null;
  diff: number | null;
  details: unknown;
}

export interface HealthScore {
  score: number;
  rating: string;
  breakdown: { metric_code: string; points: number; weight: number; included: boolean }[];
}

export interface ReviewRecommendation {
  item_id?: string;
  kind?: string;
  action?: "accept" | "remap" | "adjust" | string;
  suggested_account_id?: string;
  account_name?: string;
  confidence?: number;
  reasoning?: string;
  audit_note?: string;
  title?: string;
  auto_resolvable?: boolean;
  alternatives?: { account_id: string; account_name?: string; confidence?: number }[];
}

export interface ReviewItem {
  id: string;
  kind: "reconciliation" | "mapping" | string;
  status: string;
  created_at: string;
  payload: {
    check_code?: string;
    expected?: number;
    actual?: number;
    diff?: number;
    explanation?: string;
    label?: string;
    section?: string;
    suggested_account_id?: string;
    confidence?: number;
    document_id?: string;

    recommendation?: ReviewRecommendation;
    [k: string]: unknown;
  };
}


export interface Instruction {
  id: string;
  content: string;
  status: "pending" | "applied" | "ignored" | string;
  stage_applied: string | null;
  target_agents: string[] | null;
  orchestrator_note: string | null;
  created_at: string;
  applied_at: string | null;
}

export interface LlmStatus {
  configured_backend: string;
  resolved_backend: string;
  active_model: string;
  reasoning_model?: string | null;
  parallel_calls: boolean;
  max_concurrent_requests: number;
  keys_configured: { openai: boolean; gemini: boolean; custom: boolean };
  masked_keys: { openai: string; gemini: string; custom: string };
  models?: Record<string, string>;
}

export type AssistantResponse =
  | { type: "clarification"; question: string; options: { label: string; description: string; agent: string }[] }
  | { type: "answer"; answer: string; agent_used: string | null; status?: string };

export interface QaResponse {
  answer: string;
  citations: string[];
  route: string;
}

export interface Industry { key: string; label: string }

export interface IndustryList { source: string; as_of: string; industries: Industry[] }

export interface BenchmarkItem {
  metric_code: string;
  period_end: string;
  value: number;
  unit: string;
  p25: number;
  median: number;
  p75: number;
  quartile: 1 | 2 | 3 | 4;
  lower_is_better: boolean;
  verdict: "better" | "in_line" | "worse";
}

export interface Benchmarks { industry: string; label: string; source: string; as_of: string; items: BenchmarkItem[] }

export interface StatementRow {
  account_id: string;
  account_name: string;
  values: Record<string, number | null>;
  change: Record<string, number | null>;
  change_pct: Record<string, number | null>;
  common_size: Record<string, number | null>;
}

export interface BridgeStep { label: string; amount: number; kind: "start" | "delta" | "end"; account_id?: string | null }

/** GET /api/jobs/<id>/analysis -- the detailed statement analysis (tools/calc/detailed_analysis.py). */
export interface DetailedAnalysis {
  periods: string[];
  statements: { PL: StatementRow[]; BS: StatementRow[]; CF: StatementRow[] };
  dupont: { period: string; net_margin: number; asset_turnover: number; equity_multiplier: number; roe: number }[];
  growth: { label: string; metric_code: string; first_period: string; last_period: string; first: number; last: number; years: number; cagr: number | null }[];
  profit_bridge: { from_period: string; to_period: string; steps: BridgeStep[]; unexplained: number; reconciled: boolean } | null;
  leverage_liquidity: { period: string; working_capital: number | null; total_debt: number | null; net_debt: number | null; ebitda: number | null; net_debt_to_ebitda: number | null }[];
  bank: {
    monthly: { month: string; inflow: number; outflow: number; net: number; txn_count: number; closing_balance: number | null }[];
    top_inflows: { counterparty: string; amount: number; share: number | null }[];
    top_outflows: { counterparty: string; amount: number; share: number | null }[];
    totals: { inflow: number; outflow: number; net: number; months: number; txn_count: number; avg_monthly_net: number | null } | null;
  };
}

export interface AddDocumentsResult { job_id: string; status: string; added: string[]; skipped: string[] }
