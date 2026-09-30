// Formatting for Indian financial statements: ₹ with lakh/crore grouping, ratios as "1.84×",
// percentages stored as fractions (0.184) shown as 18.4%.

const inrGroup = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

// Negative rupee amounts use the accounting convention: (₹1.20 L), styled red by the caller.
const paren = (neg: boolean, s: string) => (neg ? `(${s})` : s);

export function formatInrCompact(value: number): string {
  const abs = Math.abs(value);
  let s: string;
  if (abs >= 1e7) s = `₹${(abs / 1e7).toFixed(abs >= 1e9 ? 0 : 2)} Cr`;
  else if (abs >= 1e5) s = `₹${(abs / 1e5).toFixed(2)} L`;
  else s = `₹${inrGroup.format(abs)}`;
  return paren(value < 0, s);
}

export function formatInrFull(value: number): string {
  return paren(value < 0, `₹${inrGroup.format(Math.abs(value))}`);
}

export function formatMetric(value: number | null | undefined, unit: string, compact = true): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  switch (unit) {
    case "%": {
      const pct = value * 100;
      return `${pct < 0 ? "−" : ""}${Math.abs(pct).toFixed(1)}%`;
    }
    case "x":
      return `${value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}×`;
    case "days":
      return `${Math.round(value)} days`;
    case "months":
      return `${value.toFixed(1)} months`;
    case "pts":
      return `${Math.round(value)} / 100`;
    case "INR":
      return compact ? formatInrCompact(value) : formatInrFull(value);
    default:
      return Number.isInteger(value) ? value.toLocaleString("en-IN") : value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export interface MetricDef {
  label: string;
  group: "Liquidity" | "Leverage & coverage" | "Profitability" | "Cost structure" | "Working capital" | "Growth & cash" | "Cash in the bank" | "Forecast & scores";
  /** true when a higher value is healthier; drives the direction of the change marker. */
  higherIsBetter: boolean;
  hint: string;
}

export const METRICS: Record<string, MetricDef> = {
  current_ratio: { label: "Current ratio", group: "Liquidity", higherIsBetter: true, hint: "Current assets ÷ current liabilities" },
  quick_ratio: { label: "Quick ratio", group: "Liquidity", higherIsBetter: true, hint: "(Current assets − inventory) ÷ current liabilities" },
  cash_ratio: { label: "Cash ratio", group: "Liquidity", higherIsBetter: true, hint: "Cash ÷ current liabilities" },
  debt_to_equity: { label: "Debt to equity", group: "Leverage & coverage", higherIsBetter: false, hint: "Total borrowings ÷ equity" },
  interest_coverage: { label: "Interest coverage", group: "Leverage & coverage", higherIsBetter: true, hint: "EBITDA ÷ finance cost" },
  dscr: { label: "Debt service coverage", group: "Leverage & coverage", higherIsBetter: true, hint: "(PBT + interest + depreciation) ÷ interest" },
  ebitda: { label: "EBITDA", group: "Profitability", higherIsBetter: true, hint: "Earnings before interest, tax, depreciation and amortisation" },
  gross_profit_pct: { label: "Gross margin", group: "Profitability", higherIsBetter: true, hint: "(Revenue − COGS) ÷ revenue" },
  ebitda_margin: { label: "EBITDA margin", group: "Profitability", higherIsBetter: true, hint: "EBITDA ÷ revenue" },
  net_profit_margin: { label: "Net margin", group: "Profitability", higherIsBetter: true, hint: "PAT ÷ revenue" },
  roe: { label: "Return on equity", group: "Profitability", higherIsBetter: true, hint: "PAT ÷ equity" },
  roce: { label: "Return on capital employed", group: "Profitability", higherIsBetter: true, hint: "EBIT ÷ capital employed" },
  asset_turnover: { label: "Asset turnover", group: "Profitability", higherIsBetter: true, hint: "Revenue ÷ total assets" },
  dso: { label: "Receivable days", group: "Working capital", higherIsBetter: false, hint: "Days sales outstanding" },
  dio: { label: "Inventory days", group: "Working capital", higherIsBetter: false, hint: "Days inventory outstanding" },
  dpo: { label: "Payable days", group: "Working capital", higherIsBetter: true, hint: "Days payables outstanding" },
  cash_conversion_cycle: { label: "Cash conversion cycle", group: "Working capital", higherIsBetter: false, hint: "DSO + DIO − DPO" },
  revenue_growth_yoy: { label: "Revenue growth", group: "Growth & cash", higherIsBetter: true, hint: "Year-on-year change in revenue" },
  pat_growth_yoy: { label: "PAT growth", group: "Growth & cash", higherIsBetter: true, hint: "Year-on-year change in profit after tax" },
  ocf_to_pat: { label: "Cash conversion (OCF ÷ PAT)", group: "Growth & cash", higherIsBetter: true, hint: "Operating cash flow ÷ PAT" },
  free_cash_flow: { label: "Free cash flow", group: "Growth & cash", higherIsBetter: true, hint: "Operating + investing cash flow" },
  revenue_forecast: { label: "Revenue forecast", group: "Forecast & scores", higherIsBetter: true, hint: "Projected revenue for the next period" },
  pat_forecast: { label: "PAT forecast", group: "Forecast & scores", higherIsBetter: true, hint: "Projected profit after tax for the next period" },
  health_score: { label: "Health score", group: "Forecast & scores", higherIsBetter: true, hint: "Rules-based score out of 100" },
  risk_score: { label: "Risk score", group: "Forecast & scores", higherIsBetter: false, hint: "Anomaly and risk-signal score; lower is safer" },
  ebit: { label: "EBIT", group: "Profitability", higherIsBetter: true, hint: "EBITDA less depreciation" },
  cogs_to_revenue: { label: "Materials cost", group: "Cost structure", higherIsBetter: false, hint: "Cost of materials ÷ revenue" },
  employee_cost_to_revenue: { label: "Employee cost", group: "Cost structure", higherIsBetter: false, hint: "Employee costs ÷ revenue" },
  other_expenses_to_revenue: { label: "Other expenses", group: "Cost structure", higherIsBetter: false, hint: "Other expenses ÷ revenue" },
  finance_cost_to_revenue: { label: "Finance cost", group: "Cost structure", higherIsBetter: false, hint: "Finance costs ÷ revenue" },
  working_capital: { label: "Working capital", group: "Liquidity", higherIsBetter: true, hint: "Current assets − current liabilities" },
  equity_multiplier: { label: "Equity multiplier", group: "Leverage & coverage", higherIsBetter: false, hint: "Total assets ÷ equity" },
  net_debt: { label: "Net debt", group: "Leverage & coverage", higherIsBetter: false, hint: "Borrowings − cash" },
  net_debt_to_ebitda: { label: "Net debt ÷ EBITDA", group: "Leverage & coverage", higherIsBetter: false, hint: "Years of EBITDA to repay net debt" },
  ebitda_growth_yoy: { label: "EBITDA growth", group: "Growth & cash", higherIsBetter: true, hint: "Year-on-year change in EBITDA" },
  revenue_cagr: { label: "Revenue growth per year", group: "Growth & cash", higherIsBetter: true, hint: "Compound annual growth" },
  ebitda_cagr: { label: "EBITDA growth per year", group: "Growth & cash", higherIsBetter: true, hint: "Compound annual growth" },
  pat_cagr: { label: "PAT growth per year", group: "Growth & cash", higherIsBetter: true, hint: "Compound annual growth" },
  total_assets_cagr: { label: "Asset growth per year", group: "Growth & cash", higherIsBetter: true, hint: "Compound annual growth" },
  net_cash_after_investing: { label: "Net cash after investing", group: "Growth & cash", higherIsBetter: true, hint: "Operating + all investing cash flows (not free cash flow)" },
  bank_closing_balance: { label: "Closing balance", group: "Cash in the bank", higherIsBetter: true, hint: "Bank balance at month end" },
  bank_inflows: { label: "Money in", group: "Cash in the bank", higherIsBetter: true, hint: "Total credits in the month" },
  bank_outflows: { label: "Money out", group: "Cash in the bank", higherIsBetter: false, hint: "Total debits in the month" },
  bank_net_flow: { label: "Net cash flow", group: "Cash in the bank", higherIsBetter: true, hint: "Money in minus money out" },
  bank_avg_monthly_inflow: { label: "Average monthly inflow", group: "Cash in the bank", higherIsBetter: true, hint: "Credits per month across the statement" },
  bank_avg_monthly_outflow: { label: "Average monthly outflow", group: "Cash in the bank", higherIsBetter: false, hint: "Debits per month across the statement" },
  bank_min_balance: { label: "Lowest balance", group: "Cash in the bank", higherIsBetter: true, hint: "Lowest running balance in the statement" },
  bank_cash_cover_months: { label: "Cash cover", group: "Cash in the bank", higherIsBetter: true, hint: "Closing balance ÷ average monthly outflow" },
  bank_top_payer_share: { label: "Largest payer's share", group: "Cash in the bank", higherIsBetter: false, hint: "Share of receipts from the single biggest payer" },
  bank_negative_month_share: { label: "Cash-negative months", group: "Cash in the bank", higherIsBetter: false, hint: "Share of months where outflows beat inflows" },
};

export const METRIC_GROUPS: MetricDef["group"][] = [
  "Profitability", "Cost structure", "Liquidity", "Leverage & coverage", "Working capital", "Growth & cash", "Cash in the bank", "Forecast & scores",
];

export function metricLabel(code: string): string {
  return METRICS[code]?.label ?? code.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function formatPeriod(iso: string): string {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

/** "FY24" for a 31-Mar year end, otherwise "Mar 24". Pass monthly for series that are
 * monthly by nature (bank flows), where a March month-end is a month, not a fiscal year. */
export function formatPeriodShort(iso: string, monthly = false): string {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  if (!monthly && d.getMonth() === 2 && d.getDate() === 31) return `FY${String(d.getFullYear()).slice(2)}`;
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z").getTime();
  const diff = (Date.now() - t) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)} d ago`;
  return new Date(t).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function formatClock(iso: string): string {
  const t = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  return t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/** Bank-statement metrics are monthly series (or keyed to the statement's last month end). */
export function isMonthlyMetric(code: string): boolean {
  return code.startsWith("bank_");
}

export function humanize(code: string): string {
  return code.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

/** Findings are stored with metric bindings ({{m:code:period}}) that the report renderer resolves
 * server-side; resolve them here too so raw placeholders never reach the screen. */
export function resolveBindings(text: string, metrics: { metric_code: string; period_end: string; value: number | null; unit: string }[]): string {
  return text.replace(/\{\{m:([a-z0-9_]+):(\d{4}-\d{2}-\d{2})\}\}/gi, (_, code: string, period: string) => {
    const m = metrics.find((x) => x.metric_code === code && x.period_end === period);
    // The sentence around a binding already names the metric; add only the period.
    const label = formatPeriodShort(period, isMonthlyMetric(code));
    return m ? `${formatMetric(m.value, m.unit)} (${label})` : `${metricLabel(code)} (${label})`;
  });
}

/** Backend titles like "Dso observation" name the metric by code; show the readable name instead. */
export function tidyTitle(title: string): string {
  return title.replace(/^([A-Za-z_]+)(\s+observation)$/i, (whole, word: string, rest: string) => {
    const code = word.toLowerCase();
    return METRICS[code] ? `${METRICS[code].label}${rest}` : whole;
  });
}
