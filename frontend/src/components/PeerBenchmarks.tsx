import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useBenchmarks, useIndustries } from "../lib/hooks";
import { formatMetric, formatPeriodShort, metricLabel } from "../lib/format";
import type { BenchmarkItem, Job } from "../lib/types";
import { useFeedback } from "./feedback";
import { ErrorNote, Skeleton } from "./ui";

const VERDICT: Record<BenchmarkItem["verdict"], string> = {
  better: "Stronger than most peers",
  in_line: "In line with peers",
  worse: "Weaker than most peers",
};

export function PeerBenchmarks({ job }: { job: Job }) {
  const industries = useIndustries();
  const bench = useBenchmarks(job.id, job, job.industry);
  const qc = useQueryClient();
  const { toast } = useFeedback();

  const setIndustry = useMutation({
    mutationFn: (industry: string) => api.updateProfile(job.id, { industry }),
    onSuccess: (updated) => {
      qc.setQueryData(["job", job.id], (old: Job | undefined) => (old ? { ...old, industry: updated.industry } : old));
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  // Weaknesses first: they are what a reviewer or lender needs to see before anything else.
  const ORDER = { worse: 0, better: 1, in_line: 2 } as const;
  const items = [...(bench.data?.items ?? [])].sort((a, b) => ORDER[a.verdict] - ORDER[b.verdict]);

  return (
    <section aria-labelledby="peers-title">
      <div className="section-head">
        <h2 className="panel-title" id="peers-title">Against industry peers</h2>
        <label className="inline-select">
          <span className="muted small">Industry</span>
          <select value={job.industry ?? ""} onChange={(e) => setIndustry.mutate(e.target.value)} disabled={setIndustry.isPending}>
            <option value="" disabled>Choose an industry</option>
            {industries.data?.industries.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
          </select>
        </label>
      </div>

      {!job.industry ? (
        <p className="muted">Choose the company's industry to see where each ratio sits against peer companies.</p>
      ) : bench.isLoading ? <Skeleton h={220} /> : bench.error ? <ErrorNote error={bench.error} /> : !items.length ? (
        <p className="muted">None of this analysis's ratios have a benchmark for this industry. Benchmarks cover statement ratios, not bank-statement cash figures.</p>
      ) : (
        <>
          <div className="peers">
            <div className="peers-legend" aria-hidden="true">
              <span><i className="lg-band" /> Middle half of peers</span>
              <span><i className="lg-median" /> Peer median</span>
              <span><i className="lg-dot" /> This company</span>
            </div>
            {items.map((it) => <PeerRow key={it.metric_code} item={it} />)}
          </div>
          <p className="source-note">
            {bench.data!.source}{bench.data!.as_of ? `, ${bench.data!.as_of}` : ""}. Latest period of each ratio. Use as context, not as the basis of a credit decision.
          </p>
        </>
      )}
    </section>
  );
}

function PeerRow({ item }: { item: BenchmarkItem }) {
  const { value, p25, median, p75, unit } = item;
  // Scale around the peer range, widened to include the company when it sits outside it.
  const lo0 = Math.min(p25, value), hi0 = Math.max(p75, value);
  const pad = (hi0 - lo0) * 0.12 || Math.abs(hi0) * 0.1 || 1;
  const lo = lo0 - pad, hi = hi0 + pad;
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;

  return (
    <div className={`peer peer-${item.verdict}`}>
      <div className="peer-name">
        <span className="peer-label">{metricLabel(item.metric_code)}</span>
        <span className="peer-range">Peers {formatMetric(p25, unit)} to {formatMetric(p75, unit)}, median {formatMetric(median, unit)}</span>
      </div>
      <div className="peer-value">
        <span className="peer-num">{formatMetric(value, unit)}</span>
        <span className="peer-period">{formatPeriodShort(item.period_end)}</span>
      </div>
      <div className="peer-track" role="img"
        aria-label={`${metricLabel(item.metric_code)} ${formatMetric(value, unit)}; peers ${formatMetric(p25, unit)} to ${formatMetric(p75, unit)}; ${VERDICT[item.verdict]}`}>
        <span className="peer-band" style={{ left: pos(p25), width: `calc(${pos(p75)} - ${pos(p25)})` }} />
        <span className="peer-median" style={{ left: pos(median) }} />
        <span className="peer-dot" style={{ left: pos(value) }} />
      </div>
      <div className="peer-verdict">{VERDICT[item.verdict]}</div>
    </div>
  );
}
