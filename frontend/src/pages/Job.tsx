import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Columns2, Download, ExternalLink, FilePlus2, FileSpreadsheet, MessageSquareText, RefreshCw, ShieldCheck, Trash2, X } from "lucide-react";
import { api, reportUrl } from "../lib/api";
import {
  refreshResults, useBenchmarks, useDetailedAnalysis, useIndustries, useInstructions, useInvalidateOnStatusChange, useJob, useResults, useReviewItems, useTasks,
} from "../lib/hooks";
import { isActive, TEMPLATES } from "../lib/pipeline";
import { formatNumber, formatPeriod, formatPeriodShort, formatRelative, humanize } from "../lib/format";
import type { Chart, Job } from "../lib/types";
import { RunLedger } from "../components/RunLedger";
import { ReviewPanel } from "../components/ReviewPanel";
import { ChatPanel } from "../components/ChatPanel";
import { AddStatementsDialog } from "../components/AddStatementsDialog";
import { PeerBenchmarks } from "../components/PeerBenchmarks";
import { StatementAnalysis } from "../components/StatementAnalysis";
import { DataExplorer } from "../components/DataExplorer";
import { Findings, HeadlineFigures, HealthRating, isForecast, MetricSpread, SummaryOpinion } from "../components/Overview";
import { EmptyState, ErrorNote, Skeleton, Spinner, StatusBadge } from "../components/ui";
import { useFeedback } from "../components/feedback";

type View = "overview" | "statements" | "run" | "report" | "charts" | "data";

function StatementsView({ job }: { job: Job }) {
  const analysis = useDetailedAnalysis(job.id, job);
  if (analysis.isLoading) return <div className="stack"><Skeleton h={260} /><Skeleton h={200} /></div>;
  if (!analysis.data) {
    return (
      <div className="stack">
        <DataExplorer job={job} />
      </div>
    );
  }
  return <StatementAnalysis analysis={analysis.data} job={job} />;
}

export function JobPage() {
  const { jobId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { data: job, error, isLoading } = useJob(jobId);
  const tasks = useTasks(jobId, job);
  const instructions = useInstructions(jobId, job);
  const review = useReviewItems(jobId, job);
  const results = useResults(jobId, job);
  useInvalidateOnStatusChange(jobId, job);
  // Wide screens open the panel by default; after that, the user's own choice sticks.
  const [chatOpen, setChatOpenState] = useState(() => {
    const saved = localStorage.getItem("finsight.chatOpen");
    const wide = window.matchMedia("(min-width: 1280px)").matches;
    return wide && saved !== "0";
  });
  const setChatOpen = (next: boolean | ((o: boolean) => boolean)) => setChatOpenState((cur) => {
    const v = typeof next === "function" ? next(cur) : next;
    if (window.matchMedia("(min-width: 1280px)").matches) localStorage.setItem("finsight.chatOpen", v ? "1" : "0");
    return v;
  });
  const [adding, setAdding] = useState(false);

  const done = job?.status === "COMPLETED";
  const requested = params.get("view") as View | null;
  const view: View = requested ?? (done ? "overview" : "run");
  const setView = (v: View) => setParams(v === (done ? "overview" : "run") ? {} : { view: v }, { replace: true });

  if (error) {
    return (
      <div className="page">
        <EmptyState title={(error as { status?: number }).status === 404 ? "This analysis doesn't exist" : "Couldn't load this analysis"}
          action={<Link to="/analyses" className="btn btn-secondary">Back to analyses</Link>}>
          {(error as Error).message}
        </EmptyState>
      </div>
    );
  }
  if (isLoading || !job) {
    return <div className="page"><Skeleton h={28} w="40%" /><div style={{ height: 16 }} /><Skeleton h={200} /></div>;
  }

  const chartsCount = results.charts.data?.length;

  return (
    <div className={`job ${chatOpen ? "job-with-chat" : ""}`}>
      <div className="job-main">
        <JobHeader job={job} onToggleChat={() => setChatOpen((o) => !o)} chatOpen={chatOpen}
          hasReport={!!results.report.data} onAddStatements={() => setAdding(true)} />
        {adding && <AddStatementsDialog job={job} onClose={() => setAdding(false)}
          onAdded={() => { setAdding(false); setParams({ view: "run" }, { replace: true }); }} />}

        {review.data && review.data.length > 0 && <ReviewPanel job={job} items={review.data} />}
        {job.status === "NEEDS_ANALYST" && (!review.data || review.data.length === 0) && (
          <div className="alert alert-attention" role="alert" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
            <div>
              <strong>Analyst Sign-Off Required:</strong> Automated verification flagged discrepancies requiring review before report certification.
            </div>
            <button className="btn btn-secondary btn-sm" onClick={() => review.refetch()}>
              Refresh Diagnostics
            </button>
          </div>
        )}
        {job.status === "FAILED" && (
          <div className="alert alert-danger" role="alert">
            <strong>The analysis stopped.</strong> {job.error || job.progress_message}
            <span> Check the run log for the agent that failed, then start a new analysis with corrected files.</span>
          </div>
        )}

        <nav className="tabs" aria-label="Analysis sections">
          {([
            ["overview", "Overview", undefined],
            ["statements", "Statements", undefined],
            ["report", "Report", undefined],
            ["charts", "Charts", chartsCount],
            ["data", "Data & checks", undefined],
            ["run", "Run log", undefined],
          ] as [View, string, number | undefined][]).map(([k, label, n]) => (
            <button key={k} className={`tab ${view === k ? "tab-on" : ""}`} aria-current={view === k ? "page" : undefined} onClick={() => setView(k)}>
              {label}{n ? <span className="tab-count">{n}</span> : null}
            </button>
          ))}
        </nav>

        <div className="view">
          {view === "overview" && <OverviewView job={job} results={results} onRun={() => setView("run")} />}
          {view === "run" && (tasks.data ? <RunLedger job={job} tasks={tasks.data} /> : <Skeleton h={300} />)}
          {view === "statements" && <StatementsView job={job} />}
          {view === "report" && <ReportView job={job} ready={!!results.report.data} loading={results.report.isLoading} />}
          {view === "charts" && <ChartsView charts={results.charts.data} loading={results.charts.isLoading} job={job} />}
          {view === "data" && <DataView job={job} results={results} />}
        </div>
      </div>

      {chatOpen && (
        <>
          <div className="chat-scrim" onClick={() => setChatOpen(false)} />
          <ChatPanel key={job.id} job={job} instructions={instructions.data ?? []} onClose={() => setChatOpen(false)} />
        </>
      )}
    </div>
  );
}

function JobHeader({ job, onToggleChat, chatOpen, hasReport, onAddStatements }: {
  job: Job; onToggleChat: () => void; chatOpen: boolean; hasReport: boolean; onAddStatements: () => void;
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { confirm, toast } = useFeedback();
  const del = useMutation({
    mutationFn: () => api.deleteJob(job.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); toast("Analysis deleted.", "success"); navigate("/analyses"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const onDelete = async () => {
    if (await confirm({
      title: "Delete this analysis?",
      body: "The uploaded statements, extracted data, metrics, findings, charts and reports will be permanently removed.",
      confirmLabel: "Delete analysis", danger: true,
    })) del.mutate();
  };
  const active = isActive(job.status);
  const docs = job.documents ?? [];
  const industryLabel = useIndustries().data?.industries.find((i) => i.key === job.industry)?.label;

  return (
    <header className="job-head">
      <div className="crumbs"><Link to="/analyses">Analyses</Link>{job.company_name && <span className="crumb-company">{job.company_name}</span>}</div>
      <div className="job-title-row">
        <h1>{job.goal || "Untitled analysis"}</h1>
        <div className="job-actions">
          <button className="btn btn-secondary btn-sm" onClick={onAddStatements} disabled={active}
            title={active ? "Available once this run finishes" : "Upload more statements and re-run"}>
            <FilePlus2 size={14} /> Add statements
          </button>
          <Link className="btn btn-secondary btn-sm" to={`/compare?a=${job.id}`}><Columns2 size={14} /> Compare</Link>
          {hasReport && (
            <details className="menu">
              <summary className="btn btn-secondary btn-sm"><Download size={14} /> Download</summary>
              <div className="menu-pop" role="menu">
                <a role="menuitem" href={reportUrl(job.id, "pdf")}>Report as PDF</a>
                <a role="menuitem" href={reportUrl(job.id, "docx")}>Report as Word</a>
              </div>
            </details>
          )}
          <button className={`btn btn-sm ${chatOpen ? "btn-secondary btn-pressed" : "btn-secondary"}`} onClick={onToggleChat} aria-pressed={chatOpen}>
            <MessageSquareText size={14} /> {active ? "Guide" : "Ask"}
          </button>
          <button className="icon-btn" onClick={onDelete} aria-label="Delete analysis" title="Delete analysis"><Trash2 size={16} /></button>
        </div>
      </div>
      <div className="job-meta">
        <StatusBadge status={job.status} />
        <span>{TEMPLATES[job.plan_template]?.label ?? job.plan_template}</span>
        {industryLabel && <span>{industryLabel}</span>}
        <span>{docs.length} {docs.length === 1 ? "statement" : "statements"}</span>
        <span>Started {formatRelative(job.created_at)}</span>
        {(job.dataset_versions ?? 1) > 1 && <span>Version {job.dataset_versions}</span>}
      </div>
      {(active || job.status === "AWAITING_REVIEW") && <StageProgress job={job} />}
    </header>
  );
}

function StageProgress({ job }: { job: Job }) {
  // Progress is one 0-100 number; these bands match the checkpoints the stage supervisors report
  // (data 5-70, analysis 75-85, delivery 88-100).
  const pct = job.progress_pct ?? 0;
  const segs = [
    { label: "Prepare the data", from: 0, to: 70 },
    { label: "Analyse", from: 70, to: 86 },
    { label: "Write the report", from: 86, to: 100 },
  ];
  return (
    <div className="progress" aria-label={`${pct}% complete`}>
      <div className="progress-segs">
        {segs.map((s) => {
          const fill = Math.max(0, Math.min(1, (pct - s.from) / (s.to - s.from)));
          return (
            <div key={s.label} className="progress-seg">
              <div className="progress-track"><div className="progress-fill" style={{ transform: `scaleX(${fill})` }} /></div>
              <span className={fill > 0 ? "progress-label-on" : ""}>{s.label}</span>
            </div>
          );
        })}
      </div>
      <div className="progress-msg">
        {job.status === "AWAITING_REVIEW" ? "Paused for your review" : <><Spinner size={12} /> {job.progress_message}</>}
        <span className="progress-pct">{pct}%</span>
      </div>
    </div>
  );
}

type Results = ReturnType<typeof useResults>;

function OverviewView({ job, results, onRun }: { job: Job; results: Results; onRun: () => void }) {
  const { metrics, findings, health } = results;
  const bench = useBenchmarks(job.id, job, job.industry);
  if (!job.dataset_version_id || (metrics.data && !metrics.data.length && isActive(job.status))) {
    return (
      <EmptyState title={job.status === "FAILED" ? "No results" : "Results appear here as the agents finish"}
        action={<button className="btn btn-secondary" onClick={onRun}>Watch the run</button>}>
        Key figures, the health rating and findings fill in once the analysis stage completes.
      </EmptyState>
    );
  }
  if (metrics.isLoading) return <div className="stack"><Skeleton h={96} /><Skeleton h={180} /><Skeleton h={320} /></div>;
  if (metrics.error) return <ErrorNote error={metrics.error} />;
  const m = metrics.data ?? [];
  const actuals = m.filter((x) => !isForecast(x.metric_code));

  return (
    <div className="overview">
      {job.status === "COMPLETED" && (
        <SummaryOpinion health={health.data} findings={findings.data ?? []} benchmarks={bench.data} metrics={m} />
      )}
      <HeadlineFigures metrics={m} />
      <div className="overview-grid">
        <div className="overview-primary">
          {findings.data && findings.data.length > 0 ? <Findings findings={findings.data} metrics={m} /> : (
            <section><h2 className="panel-title">What needs attention</h2><p className="all-clear">No findings were raised.</p></section>
          )}
        </div>
        <div className="overview-secondary">
          {health.data && <HealthRating health={health.data} />}
          <VerifiedNote job={job} />
        </div>
      </div>
      <PeerBenchmarks job={job} />
      {actuals.length > 0 && (
        <section>
          <div className="section-head"><h2 className="panel-title">Key ratios</h2><span className="muted small">Latest four periods</span></div>
          <MetricSpread metrics={actuals} />
        </section>
      )}
    </div>
  );
}

function VerifiedNote({ job }: { job: Job }) {
  if (job.status !== "COMPLETED") return null;
  return (
    <div className="verified">
      <ShieldCheck size={18} />
      <div>
        <strong>Figures verified</strong>
        <p>Every number in the report is bound to a computed metric and checked by the verifier before release.</p>
      </div>
    </div>
  );
}

function ReportView({ job, ready, loading }: { job: Job; ready: boolean; loading: boolean }) {
  const [version, setVersion] = useState(0);
  const qc = useQueryClient();
  useEffect(() => setVersion((v) => v + 1), [job.updated_at]);
  if (loading) return <Skeleton h={500} />;
  if (!ready) {
    return (
      <EmptyState title={isActive(job.status) ? "The report is being written" : "No report yet"}>
        {isActive(job.status) ? "It appears here once the verifier has checked every figure." : "The report is produced in the final stage. This analysis didn't reach it."}
      </EmptyState>
    );
  }
  return (
    <div className="report">
      <div className="report-bar">
        <span className="muted small">Executive report</span>
        <div className="report-bar-actions">
          <button className="btn btn-ghost btn-sm" onClick={() => { refreshResults(qc, job.id); setVersion((v) => v + 1); }}><RefreshCw size={14} /> Reload</button>
          <a className="btn btn-ghost btn-sm" href={reportUrl(job.id, "html")} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open in new tab</a>
        </div>
      </div>
      <iframe key={version} className="report-frame" title="Executive report" src={`${reportUrl(job.id, "html")}&v=${version}`} />
    </div>
  );
}

function ChartsView({ charts, loading, job }: { charts: Chart[] | undefined; loading: boolean; job: Job }) {
  const [zoom, setZoom] = useState<Chart | null>(null);
  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setZoom(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoom]);
  if (loading) return <div className="charts">{[0, 1].map((i) => <Skeleton key={i} h={260} />)}</div>;
  if (!charts?.length) {
    return <EmptyState title="No charts yet">{isActive(job.status) ? "Charts are drawn in the final stage." : "This analysis didn't produce charts."}</EmptyState>;
  }
  return (
    <>
      <div className="charts">
        {charts.map((c) => (
          <figure key={c.chart_id} className="chart">
            <button className="chart-img" onClick={() => setZoom(c)} aria-label={`Enlarge ${c.title}`}><img src={c.png_base64} alt={c.title} loading="lazy" /></button>
            <figcaption>
              <strong>{c.title}</strong>
              {c.takeaway && <span className="chart-takeaway">{c.takeaway}</span>}
              {c.caption && c.caption !== c.takeaway && <span>{c.caption}</span>}
            </figcaption>
          </figure>
        ))}
      </div>
      {zoom && (
        <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && setZoom(null)}>
          <figure className="lightbox" role="dialog" aria-modal="true" aria-label={zoom.title}>
            <button className="icon-btn lightbox-close" onClick={() => setZoom(null)} aria-label="Close"><X size={18} /></button>
            <img src={zoom.png_base64} alt={zoom.title} />
            <figcaption><strong>{zoom.title}</strong>{zoom.caption && <span>{zoom.caption}</span>}</figcaption>
          </figure>
        </div>
      )}
    </>
  );
}

const CHECK_LABEL: Record<string, { name: string; rule: string }> = {
  BS_BALANCE: { name: "Balance sheet balances", rule: "Total assets equal total equity and liabilities." },
  PL_SUBTOTALS: { name: "P&L adds up", rule: "Profit after tax recomputed from its components matches the stated figure." },
  PL_BS_LINK: { name: "Profit carries into reserves", rule: "Opening reserves plus profit roughly equal closing reserves." },
  CF_CASH_TIE: { name: "Cash flow ties to cash", rule: "Opening cash plus net change equals closing cash and the balance sheet." },
  BANK_RUNNING: { name: "Bank balance runs correctly", rule: "Each balance equals the previous one plus credits minus debits." },
  DUPLICATES: { name: "No duplicate files", rule: "No statement was uploaded twice." },
  NO_FACTS: { name: "Usable figures found", rule: "At least one statement produced figures to analyse." },
};

function checkPeriod(details: unknown): string | null {
  const p = details && typeof details === "object" ? (details as { period_end?: unknown }).period_end : null;
  return typeof p === "string" ? p : null;
}

function DataView({ job, results }: { job: Job; results: Results }) {
  const checks = results.validation.data ?? [];
  const passed = checks.filter((c) => c.status === "pass").length;
  const docs = job.documents ?? [];
  return (
    <div className="data-view">
      <section>
        <div className="section-head"><h2 className="panel-title">Source statements</h2></div>
        <div className="table-card">
          <table className="table">
            <thead><tr><th>File</th><th>Identified as</th><th>Period end</th><th>Status</th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td><span className="file-cell"><FileSpreadsheet size={15} /> {d.filename}</span></td>
                  <td>{d.doc_type ? humanize(d.doc_type).replace("Pnl", "Profit & loss") : <span className="muted">Not yet classified</span>}</td>
                  <td className="nowrap">{d.period_end ? formatPeriod(d.period_end) : "—"}</td>
                  <td className="muted">{humanize(d.status)}</td>
                </tr>
              ))}
              {!docs.length && <tr><td colSpan={4} className="muted center">No documents.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="section-head">
          <h2 className="panel-title">Reconciliation checks</h2>
          {checks.length > 0 && <span className="muted small">{passed} of {checks.length} tie out</span>}
        </div>
        {!job.dataset_version_id ? <p className="muted">Checks run once the statements are extracted.</p> : !checks.length ? <p className="muted">No checks recorded.</p> : (
          <div className="table-card">
            <table className="table">
              <thead><tr><th>Check</th><th className="num">Expected</th><th className="num">Found</th><th className="num">Difference</th><th>Result</th></tr></thead>
              <tbody>
                {checks.map((c, i) => (
                  <tr key={c.check_code + i}>
                    <td>
                      <span className="check-name">{CHECK_LABEL[c.check_code]?.name ?? humanize(c.check_code)}</span>
                      <span className="row-sub">
                        {checkPeriod(c.details) && <>{formatPeriodShort(checkPeriod(c.details)!)}. </>}
                        {CHECK_LABEL[c.check_code]?.rule}
                      </span>
                    </td>
                    <td className="num">{formatNumber(c.expected)}</td>
                    <td className="num">{formatNumber(c.actual)}</td>
                    <td className={`num ${c.diff ? "neg" : ""}`}>{formatNumber(c.diff)}</td>
                    <td><span className={`check check-${c.status}`}>{c.status === "pass" ? "Ties out" : humanize(c.status)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <DataExplorer job={job} />
      </section>

      {results.metrics.data && results.metrics.data.length > 0 && (
        <section>
          <div className="section-head"><h2 className="panel-title">All ratios</h2><span className="muted small">Every period computed</span></div>
          <MetricSpread metrics={results.metrics.data.filter((x) => !isForecast(x.metric_code))} maxPeriods={12} />
        </section>
      )}

      {results.metrics.data?.some((x) => isForecast(x.metric_code)) && (
        <section>
          <div className="section-head"><h2 className="panel-title">Forecast</h2><span className="muted small">Projected by the forecast agent, not reported figures</span></div>
          <MetricSpread metrics={results.metrics.data.filter((x) => isForecast(x.metric_code))} />
        </section>
      )}

      <section className="job-ids">
        <span>Analysis ID</span><code>{job.id}</code>
        {job.dataset_version_id && <><span>Dataset version</span><code>{job.dataset_version_id}</code></>}
      </section>
    </div>
  );
}
