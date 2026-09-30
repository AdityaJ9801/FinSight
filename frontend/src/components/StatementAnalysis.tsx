import { useState } from "react";
import { formatInrCompact, formatPeriodShort } from "../lib/format";
import type { BridgeStep, DetailedAnalysis, StatementRow } from "../lib/types";

const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(digits)}%`;
const times = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v.toFixed(2)}×`);
const money = (v: number | null | undefined) => (v === null || v === undefined ? "–" : formatInrCompact(v));
const signed = (v: number) => (v > 0 ? "+" : "") + formatInrCompact(v).replace(/^\((.*)\)$/, "−$1");
const fy = (iso: string) => formatPeriodShort(iso);

/** Everything the detailed-analytics agent computed, laid out as working papers. */
export function StatementAnalysis({ analysis }: { analysis: DetailedAnalysis }) {
  const hasStatements = analysis.statements.PL.length + analysis.statements.BS.length + analysis.statements.CF.length > 0;
  return (
    <div className="sa">
      {analysis.profit_bridge && <ProfitBridge bridge={analysis.profit_bridge} />}
      {(analysis.dupont.length > 0 || analysis.growth.length > 0) && (
        <div className="sa-grid">
          {analysis.dupont.length > 0 && <DuPont rows={analysis.dupont} />}
          {analysis.growth.length > 0 && <Growth rows={analysis.growth} />}
        </div>
      )}
      {hasStatements && <Statements analysis={analysis} />}
      {analysis.leverage_liquidity.length > 0 && <LeverageLiquidity rows={analysis.leverage_liquidity} />}
      {analysis.bank.totals && <BankFlows bank={analysis.bank} />}
    </div>
  );
}

function ProfitBridge({ bridge }: { bridge: NonNullable<DetailedAnalysis["profit_bridge"]> }) {
  const deltas = bridge.steps.filter((s) => s.kind === "delta");
  const max = Math.max(...deltas.map((s) => Math.abs(s.amount)), 1);
  const ordered: BridgeStep[] = [
    bridge.steps[0],
    ...[...deltas].sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount)),
    bridge.steps[bridge.steps.length - 1],
  ];
  return (
    <section aria-labelledby="bridge-title">
      <div className="section-head">
        <h2 className="panel-title" id="bridge-title">How profit moved, {fy(bridge.from_period)} to {fy(bridge.to_period)}</h2>
        <span className="muted small">Each line's effect on profit after tax, largest first</span>
      </div>
      <div className="bridge">
        {ordered.map((s, i) => {
          const total = s.kind !== "delta";
          const w = total ? 0 : (Math.abs(s.amount) / max) * 50;
          return (
            <div key={i} className={`bridge-row ${total ? "bridge-total" : ""}`}>
              <span className="bridge-label">{total ? `Profit after tax, ${fy(s.label.replace(/^PAT\s*/, ""))}` : s.label}</span>
              <span className={`bridge-amt ${total ? "" : s.amount >= 0 ? "delta-good" : "delta-bad"}`}>
                {total ? money(s.amount) : signed(s.amount)}
              </span>
              <span className="bridge-bar" aria-hidden="true">
                {!total && <span className={s.amount >= 0 ? "bar-pos" : "bar-neg"}
                  style={s.amount >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />}
              </span>
            </div>
          );
        })}
      </div>
      {!bridge.reconciled && (
        <p className="source-note attention-text">
          The movements don't fully explain the change in profit ({money(bridge.unexplained)} unexplained).
          Check the P&amp;L reconciliation in Data &amp; checks before relying on this bridge.
        </p>
      )}
    </section>
  );
}

function DuPont({ rows }: { rows: DetailedAnalysis["dupont"] }) {
  const shown = rows.slice(-4);
  return (
    <section className="panel" aria-labelledby="dupont-title">
      <h2 className="panel-title" id="dupont-title">What drives return on equity</h2>
      <p className="muted small">Return on equity = net margin × asset turnover × equity multiplier.</p>
      <table className="mini">
        <thead><tr><th scope="col" /> {shown.map((r) => <th key={r.period} scope="col" className="num">{fy(r.period)}</th>)}</tr></thead>
        <tbody>
          <tr><th scope="row">Net margin</th>{shown.map((r) => <td key={r.period} className="num">{pct(r.net_margin)}</td>)}</tr>
          <tr><th scope="row">× Asset turnover</th>{shown.map((r) => <td key={r.period} className="num">{times(r.asset_turnover)}</td>)}</tr>
          <tr><th scope="row">× Equity multiplier</th>{shown.map((r) => <td key={r.period} className="num">{times(r.equity_multiplier)}</td>)}</tr>
          <tr className="mini-total"><th scope="row">= Return on equity</th>{shown.map((r) => <td key={r.period} className="num">{pct(r.roe)}</td>)}</tr>
        </tbody>
      </table>
    </section>
  );
}

function Growth({ rows }: { rows: DetailedAnalysis["growth"] }) {
  return (
    <section className="panel" aria-labelledby="growth-title">
      <h2 className="panel-title" id="growth-title">Growth per year</h2>
      <p className="muted small">Compound annual growth between the first and last period.</p>
      <table className="mini">
        <tbody>
          {rows.map((g) => (
            <tr key={g.metric_code}>
              <th scope="row">{g.label}<span className="mini-sub">{money(g.first)} to {money(g.last)}, {fy(g.first_period)} to {fy(g.last_period)}</span></th>
              <td className={`num mini-big ${g.cagr === null ? "muted" : g.cagr >= 0 ? "delta-good" : "delta-bad"}`}>
                {g.cagr === null ? "n/a" : pct(g.cagr)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

type StmtKey = "PL" | "BS" | "CF";
type Mode = "amounts" | "common" | "change";
const STMT_LABEL: Record<StmtKey, string> = { PL: "Profit & loss", BS: "Balance sheet", CF: "Cash flow" };
const COMMON_LABEL: Record<StmtKey, string> = { PL: "% of revenue", BS: "% of total assets", CF: "" };

function Statements({ analysis }: { analysis: DetailedAnalysis }) {
  const available = (["PL", "BS", "CF"] as StmtKey[]).filter((k) => analysis.statements[k].length);
  const [stmt, setStmt] = useState<StmtKey>(available[0]);
  const [mode, setMode] = useState<Mode>("amounts");
  const rows = analysis.statements[stmt];
  const periods = analysis.periods.filter((p) => rows.some((r) => r.values[p] !== null && r.values[p] !== undefined)).slice(-4);
  const effectiveMode: Mode = mode === "common" && stmt === "CF" ? "amounts" : mode;

  const cell = (r: StatementRow, p: string, i: number) => {
    if (effectiveMode === "common") return pct(r.common_size[p]);
    if (effectiveMode === "change") return i === 0 ? "" : pct(r.change_pct[p]);
    return money(r.values[p]);
  };

  return (
    <section aria-labelledby="stmt-title">
      <div className="section-head">
        <h2 className="panel-title" id="stmt-title">Statements</h2>
        <div className="stmt-controls">
          <div className="seg" role="tablist" aria-label="Statement">
            {available.map((k) => (
              <button key={k} role="tab" aria-selected={stmt === k} className={stmt === k ? "seg-on" : ""} onClick={() => setStmt(k)}>{STMT_LABEL[k]}</button>
            ))}
          </div>
          <div className="seg" role="tablist" aria-label="Show">
            {(["amounts", "common", "change"] as Mode[]).filter((m) => !(m === "common" && stmt === "CF")).map((m) => (
              <button key={m} role="tab" aria-selected={effectiveMode === m} className={effectiveMode === m ? "seg-on" : ""} onClick={() => setMode(m)}>
                {m === "amounts" ? "Amounts" : m === "common" ? COMMON_LABEL[stmt] : "Change"}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="spread-wrap">
        <table className="spread">
          <thead>
            <tr>
              <th scope="col">Line item</th>
              {periods.map((p) => <th key={p} scope="col" className="num">{fy(p)}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isTotal = /total|profit after tax|^pat$/i.test(r.account_name) || /TOTAL|\.PAT$/.test(r.account_id);
              return (
                <tr key={r.account_id} className={isTotal ? "stmt-total" : ""}>
                  <th scope="row">{r.account_name}</th>
                  {periods.map((p, i) => {
                    const v = effectiveMode === "change" ? r.change_pct[p] : effectiveMode === "common" ? r.common_size[p] : r.values[p];
                    const neg = typeof v === "number" && v < 0;
                    const cls = effectiveMode === "change" && i > 0 && typeof v === "number" ? (v >= 0 ? "delta-good" : "delta-bad") : neg ? "neg" : "";
                    return <td key={p} className={`num ${cls}`}>{cell(r, p, i)}</td>;
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {effectiveMode === "change" && <p className="source-note">Change against the previous period. Green and red show direction only, not whether the move is good for that line.</p>}
    </section>
  );
}

function LeverageLiquidity({ rows }: { rows: DetailedAnalysis["leverage_liquidity"] }) {
  const shown = rows.slice(-4);
  return (
    <section aria-labelledby="lev-title">
      <div className="section-head"><h2 className="panel-title" id="lev-title">Debt and working capital</h2></div>
      <div className="spread-wrap">
        <table className="spread">
          <thead><tr><th scope="col" />{shown.map((r) => <th key={r.period} scope="col" className="num">{fy(r.period)}</th>)}</tr></thead>
          <tbody>
            <tr><th scope="row">Working capital</th>{shown.map((r) => <td key={r.period} className={`num ${(r.working_capital ?? 0) < 0 ? "neg" : ""}`}>{money(r.working_capital)}</td>)}</tr>
            <tr><th scope="row">Total borrowings</th>{shown.map((r) => <td key={r.period} className="num">{money(r.total_debt)}</td>)}</tr>
            <tr><th scope="row">Net debt</th>{shown.map((r) => <td key={r.period} className="num">{(r.net_debt ?? 0) < 0 ? <span className="delta-good">Net cash {money(Math.abs(r.net_debt!))}</span> : money(r.net_debt)}</td>)}</tr>
            <tr><th scope="row">Net debt ÷ EBITDA</th>{shown.map((r) => <td key={r.period} className="num">{r.net_debt_to_ebitda === null ? "–" : r.net_debt_to_ebitda < 0 ? "Net cash" : times(r.net_debt_to_ebitda)}</td>)}</tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

function BankFlows({ bank }: { bank: DetailedAnalysis["bank"] }) {
  const t = bank.totals!;
  const maxFlow = Math.max(...bank.monthly.map((m) => Math.max(m.inflow, m.outflow)), 1);
  return (
    <section aria-labelledby="bank-title">
      <div className="section-head">
        <h2 className="panel-title" id="bank-title">Bank flows</h2>
        <span className="muted small">{t.months} months, {t.txn_count} transactions</span>
      </div>
      <div className="bank-summary">
        <div><span>Money in</span><strong>{money(t.inflow)}</strong></div>
        <div><span>Money out</span><strong>{money(t.outflow)}</strong></div>
        <div><span>Net</span><strong className={t.net < 0 ? "neg" : ""}>{money(t.net)}</strong></div>
        <div><span>Average net per month</span><strong className={(t.avg_monthly_net ?? 0) < 0 ? "neg" : ""}>{money(t.avg_monthly_net)}</strong></div>
      </div>
      <div className="spread-wrap">
        <table className="spread bank-table">
          <thead><tr><th scope="col">Month</th><th scope="col" className="num">In</th><th scope="col" className="num">Out</th><th scope="col" className="num">Net</th><th scope="col" className="num">Closing balance</th><th scope="col"><span className="sr-only">In and out</span></th></tr></thead>
          <tbody>
            {bank.monthly.map((m) => (
              <tr key={m.month}>
                <th scope="row">{new Date(m.month + "-01T00:00:00").toLocaleDateString("en-IN", { month: "short", year: "numeric" })}</th>
                <td className="num">{money(m.inflow)}</td>
                <td className="num">{money(m.outflow)}</td>
                <td className={`num ${m.net < 0 ? "neg" : ""}`}>{money(m.net)}</td>
                <td className="num">{money(m.closing_balance)}</td>
                <td className="flow-bars" aria-hidden="true">
                  <span className="flow-in" style={{ width: `${(m.inflow / maxFlow) * 100}%` }} />
                  <span className="flow-out" style={{ width: `${(m.outflow / maxFlow) * 100}%` }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="sa-grid">
        <Counterparties title="Largest sources of money" rows={bank.top_inflows} />
        <Counterparties title="Largest payments" rows={bank.top_outflows} />
      </div>
    </section>
  );
}

function Counterparties({ title, rows }: { title: string; rows: DetailedAnalysis["bank"]["top_inflows"] }) {
  if (!rows.length) return null;
  return (
    <div className="panel">
      <h3 className="panel-subtitle">{title}</h3>
      <table className="mini">
        <tbody>
          {rows.map((r) => (
            <tr key={r.counterparty}>
              <th scope="row">{r.counterparty}</th>
              <td className="num">{money(r.amount)}</td>
              <td className="num muted">{pct(r.share, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
