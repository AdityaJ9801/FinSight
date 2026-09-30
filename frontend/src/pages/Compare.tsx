import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight } from "lucide-react";
import { api } from "../lib/api";
import { useIndustries, useJobs } from "../lib/hooks";
import { TEMPLATES } from "../lib/pipeline";
import { formatMetric, formatPeriodShort, formatRelative, isMonthlyMetric, METRIC_GROUPS, METRICS, metricLabel } from "../lib/format";
import type { Job, Metric } from "../lib/types";
import { changeText, direction, seriesByMetric } from "../components/Overview";
import { EmptyState, ErrorNote, Skeleton } from "../components/ui";

function jobLabel(j: Job) {
  return j.company_name ? `${j.company_name}: ${j.goal}` : j.goal || "Untitled analysis";
}

function useSide(id: string | null) {
  const enabled = !!id;
  const job = useQuery({ queryKey: ["job", id], queryFn: () => api.getJob(id!), enabled });
  const ready = enabled && !!job.data?.dataset_version_id;
  const metrics = useQuery({ queryKey: ["metrics", id], queryFn: () => api.metrics(id!), enabled: ready });
  const health = useQuery({ queryKey: ["health", id], queryFn: () => api.health(id!), enabled: ready, retry: false });
  const findings = useQuery({ queryKey: ["findings", id], queryFn: () => api.findings(id!), enabled: ready });
  return { job, metrics, health, findings };
}

type Latest = { value: number; unit: string; period: string };

function latestByCode(metrics: Metric[] | undefined): Map<string, Latest> {
  const out = new Map<string, Latest>();
  if (!metrics) return out;
  for (const [code, points] of seriesByMetric(metrics)) {
    const withValue = points.filter((p) => p.value !== null);
    const last = withValue[withValue.length - 1];
    if (last) out.set(code, { value: last.value!, unit: last.unit, period: last.period });
  }
  return out;
}

export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const a = params.get("a");
  const b = params.get("b");
  const jobs = useJobs();
  const A = useSide(a);
  const B = useSide(b);

  const choices = (jobs.data ?? []).filter((j) => j.dataset_version_id);
  const set = (key: "a" | "b", value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  const swap = () => setParams({ ...(b ? { a: b } : {}), ...(a ? { b: a } : {}) }, { replace: true });

  const la = useMemo(() => latestByCode(A.metrics.data), [A.metrics.data]);
  const lb = useMemo(() => latestByCode(B.metrics.data), [B.metrics.data]);
  const groups = useMemo(() => {
    const codes = new Set([...la.keys(), ...lb.keys()]);
    const known = METRIC_GROUPS.map((g) => ({
      group: g, codes: Object.keys(METRICS).filter((c) => METRICS[c].group === g && codes.has(c) && !c.endsWith("_forecast")),
    }));
    return known.filter((g) => g.codes.length);
  }, [la, lb]);

  const both = a && b;
  const loading = both && (A.metrics.isLoading || B.metrics.isLoading || A.job.isLoading || B.job.isLoading);
  const error = A.job.error || B.job.error || A.metrics.error || B.metrics.error;

  return (
    <div className="page page-wide">
      <header className="page-head">
        <h1>Compare analyses</h1>
        <p className="lede">Put two analyses side by side: this year against last, or one company against another.</p>
      </header>

      <div className="compare-pick">
        <PickSide label="A" value={a} jobs={choices} onChange={(v) => set("a", v)} other={b} />
        <button className="icon-btn compare-swap" onClick={swap} disabled={!a && !b} aria-label="Swap A and B" title="Swap A and B"><ArrowLeftRight size={16} /></button>
        <PickSide label="B" value={b} jobs={choices} onChange={(v) => set("b", v)} other={a} />
      </div>

      {jobs.isLoading ? <Skeleton h={120} /> : choices.length < 2 ? (
        <EmptyState title="You need two finished analyses to compare" action={<Link to="/" className="btn btn-primary">Start an analysis</Link>}>
          Comparison uses the computed ratios, so each analysis must have got past the data stage.
        </EmptyState>
      ) : !both ? (
        <p className="muted">Choose an analysis for {a ? "B" : b ? "A" : "A and B"} to see the comparison.</p>
      ) : error ? <ErrorNote error={error} /> : loading ? <Skeleton h={320} /> : (
        <>
          <div className="compare-heads">
            <SideSummary tag="A" side={A} />
            <SideSummary tag="B" side={B} />
          </div>

          <div className="spread-wrap">
            <table className="spread compare-table">
              <thead>
                <tr>
                  <th scope="col">Ratio</th>
                  <th scope="col" className="num">A</th>
                  <th scope="col" className="num">B</th>
                  <th scope="col" className="num">B against A</th>
                  <th scope="col">Stronger</th>
                </tr>
              </thead>
              {groups.map(({ group, codes }) => (
                <tbody key={group}>
                  <tr className="spread-group"><th colSpan={5} scope="colgroup">{group}</th></tr>
                  {codes.map((code) => {
                    const va = la.get(code), vb = lb.get(code);
                    const better = va && vb ? direction(code, va.value, vb.value) : null;
                    return (
                      <tr key={code}>
                        <th scope="row" title={METRICS[code]?.hint}>{metricLabel(code)}</th>
                        <td className={`num ${va && va.unit === "INR" && va.value < 0 ? "neg" : ""}`}>
                          {va ? <>{formatMetric(va.value, va.unit)}<span className="cell-period">{formatPeriodShort(va.period, isMonthlyMetric(code))}</span></> : <span className="muted">—</span>}
                        </td>
                        <td className={`num ${vb && vb.unit === "INR" && vb.value < 0 ? "neg" : ""}`}>
                          {vb ? <>{formatMetric(vb.value, vb.unit)}<span className="cell-period">{formatPeriodShort(vb.period, isMonthlyMetric(code))}</span></> : <span className="muted">—</span>}
                        </td>
                        <td className={`num ${better === null ? "muted" : better ? "delta-good" : "delta-bad"}`}>
                          {va && vb ? changeText(va.unit, va.value, vb.value) : "—"}
                        </td>
                        <td>{va && vb ? (better === null ? <span className="muted">Level</span> : <span className={`stronger stronger-${better ? "b" : "a"}`}>{better ? "B" : "A"}</span>) : <span className="muted">Only in {va ? "A" : "B"}</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              ))}
            </table>
          </div>
          <p className="source-note">Each side uses its own latest period, shown under each figure. "Stronger" accounts for direction: lower is stronger for leverage, receivable, inventory and cash-cycle days.</p>
        </>
      )}
    </div>
  );
}

function PickSide({ label, value, jobs, onChange, other }: { label: string; value: string | null; jobs: Job[]; onChange: (v: string) => void; other: string | null }) {
  return (
    <label className="compare-side">
      <span className="compare-tag">{label}</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} aria-label={`Analysis ${label}`}>
        <option value="">Choose an analysis</option>
        {jobs.map((j) => (
          <option key={j.id} value={j.id} disabled={j.id === other}>{jobLabel(j)} ({formatRelative(j.created_at)})</option>
        ))}
      </select>
    </label>
  );
}

function SideSummary({ tag, side }: { tag: string; side: ReturnType<typeof useSide> }) {
  const job = side.job.data;
  const industry = useIndustries().data?.industries.find((i) => i.key === job?.industry)?.label;
  if (!job) return null;
  const counts = { error: 0, warn: 0 } as Record<string, number>;
  (side.findings.data ?? []).forEach((f) => { counts[f.severity] = (counts[f.severity] ?? 0) + 1; });
  return (
    <div className="compare-head">
      <div className="compare-head-top">
        <span className="compare-tag">{tag}</span>
        <Link to={`/analyses/${job.id}`} className="compare-title">{job.company_name || job.goal}</Link>
      </div>
      <div className="compare-meta">
        {job.company_name && <span>{job.goal}</span>}
        <span>{TEMPLATES[job.plan_template]?.label ?? job.plan_template}{industry ? `, ${industry}` : ""}</span>
      </div>
      <dl className="compare-stats">
        <div>
          <dt>Health</dt>
          <dd>{side.health.data ? <>{side.health.data.score}<small> {side.health.data.rating}</small></> : "—"}</dd>
          {side.health.data && (() => {
            const b = side.health.data.breakdown;
            const n = b.filter((x) => x.included).length;
            return n < b.length ? <span className="compare-caveat">From {n} of {b.length} ratios</span> : null;
          })()}
        </div>
        <div><dt>Critical findings</dt><dd className={counts.error ? "neg" : ""}>{counts.error}</dd></div>
        <div><dt>To watch</dt><dd>{counts.warn}</dd></div>
      </dl>
    </div>
  );
}
