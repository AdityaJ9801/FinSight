import { useState } from "react";
import { AlertTriangle, Check, ChevronRight, Minus, X } from "lucide-react";
import { agentDef, agentsFor, isActive, STAGE_LABEL, type AgentDef, type Stage } from "../lib/pipeline";
import { formatClock } from "../lib/format";
import type { Job, TaskRun } from "../lib/types";
import { Spinner } from "./ui";

type RowState = "done" | "partial" | "failed" | "review" | "running" | "pending" | "skipped";

const STAGE_ORDER: Record<string, number> = { data: 0, analysis: 1, delivery: 2, done: 3, failed: 3 };

function worst(runs: TaskRun[]): RowState {
  if (runs.some((r) => r.status === "failed")) return "failed";
  if (runs.some((r) => r.status === "needs_review")) return "review";
  if (runs.some((r) => r.status === "partial")) return "partial";
  return "done";
}

function StateMark({ state }: { state: RowState }) {
  switch (state) {
    case "done": return <span className="mark mark-done" title="Done"><Check size={12} strokeWidth={3} /></span>;
    case "partial": return <span className="mark mark-partial" title="Partially done"><Minus size={12} strokeWidth={3} /></span>;
    case "review": return <span className="mark mark-partial" title="Needs review"><AlertTriangle size={11} strokeWidth={2.5} /></span>;
    case "failed": return <span className="mark mark-failed" title="Failed"><X size={12} strokeWidth={3} /></span>;
    case "running": return <span className="mark mark-running" title="In progress"><Spinner size={12} /></span>;
    case "skipped": return <span className="mark mark-skipped" title="Didn't run" />;
    default: return <span className="mark mark-pending" title="Waiting" />;
  }
}

const STATE_TEXT: Record<RowState, string> = {
  done: "Done", partial: "Partial", failed: "Failed", review: "Needs review",
  running: "Working", pending: "Waiting", skipped: "Didn't run",
};

/** Runs recorded before the agents wrote plain-English summaries read like
 * "ratio_trend: computed 28 metric points, 4 findings."; show those the new way. */
function plainSummary(s: string | undefined): string | undefined {
  const m = s?.match(/^[a-z_]+: computed (\d+) metric points?, (\d+) findings?\.?$/);
  if (!m) return s;
  return `Computed ${m[1]} figures and raised ${m[2]} finding${m[2] === "1" ? "" : "s"}.`;
}

const utc = (iso: string) => Date.parse(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");

/** After statements are added, the trace still holds earlier versions' runs (kept for audit);
 * progress views show the current version's run only. */
export function currentRunTasks(job: Job, tasks: TaskRun[]): TaskRun[] {
  if (!job.run_started_at) return tasks;
  const since = utc(job.run_started_at) - 1000;
  return tasks.filter((t) => utc(t.created_at) >= since);
}

export function RunLedger({ job, tasks: allTasks }: { job: Job; tasks: TaskRun[] }) {
  const planned = agentsFor(job.plan_template);
  const tasks = currentRunTasks(job, allTasks);
  const earlier = allTasks.length - tasks.length;
  const byAgent = new Map<string, TaskRun[]>();
  for (const t of tasks) byAgent.set(t.agent, [...(byAgent.get(t.agent) ?? []), t]);

  // Agents that ran but aren't in the plan (on-demand re-runs, orchestrator notes) still belong in the ledger.
  const extra = [...byAgent.keys()].filter((a) => !planned.some((p) => p.id === a)).map(agentDef);
  const rows = [...planned, ...extra];

  const active = isActive(job.status);
  const currentStage = STAGE_ORDER[job.stage] ?? 0;
  const stages: Stage[] = ["data", "analysis", "delivery"];

  const rowState = (a: AgentDef): RowState => {
    const runs = byAgent.get(a.id);
    if (runs?.length) return worst(runs);
    const s = STAGE_ORDER[a.stage];
    if (active && s === currentStage) return "running";
    // A stage that has stopped (review, failure, completion) won't run its remaining agents.
    if (s < currentStage || job.status === "COMPLETED" || s === currentStage) return "skipped";
    return "pending";
  };

  return (
    <div className="ledger">
      {earlier > 0 && (
        <p className="ledger-note">Showing version {job.dataset_versions ?? 2} of this analysis. {earlier} agent run{earlier === 1 ? "" : "s"} from earlier versions {earlier === 1 ? "is" : "are"} kept in the audit trail.</p>
      )}
      {stages.map((stage, i) => {
        const stageRows = rows.filter((r) => r.stage === stage);
        const idx = STAGE_ORDER[stage];
        const stageState = job.status === "FAILED" && idx === currentStage ? "failed"
          : idx < currentStage || job.status === "COMPLETED" ? "done"
          : idx === currentStage ? (job.status === "AWAITING_REVIEW" ? "attention" : active ? "running" : "idle")
          : "idle";
        return (
          <section key={stage} className={`ledger-stage ledger-stage-${stageState}`}>
            <header className="ledger-stage-head">
              <span className="ledger-stage-num">{i + 1}</span>
              <h3>{STAGE_LABEL[stage]}</h3>
              <span className="ledger-stage-state">
                {stageState === "done" ? "Complete" : stageState === "running" ? "In progress" : stageState === "attention" ? "Waiting for your review" : stageState === "failed" ? "Stopped" : "Not started"}
              </span>
            </header>
            <ol className="ledger-rows">
              {stageRows.map((a) => <LedgerRow key={a.id} agent={a} runs={byAgent.get(a.id) ?? []} state={rowState(a)} />)}
            </ol>
          </section>
        );
      })}
    </div>
  );
}

function LedgerRow({ agent, runs, state }: { agent: AgentDef; runs: TaskRun[]; state: RowState }) {
  const [open, setOpen] = useState(false);
  const latest = runs[runs.length - 1];
  const confs = runs.map((r) => r.confidence).filter((c): c is number => c !== null && c !== undefined);
  const conf = confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : null;
  const issues = runs.flatMap((r) => r.issues ?? []);
  const expandable = runs.length > 0;
  // A module that had nothing to work on (e.g. GST with no GST returns) isn't a partial
  // failure; show it as not applicable rather than as a low-confidence result.
  const notApplicable = state === "partial" && /not applicable|skipping|no .{1,40} uploaded/i.test(latest?.summary ?? "");
  const shown: RowState = notApplicable ? "skipped" : state;

  return (
    <li className={`ledger-row ledger-row-${shown}`}>
      <button className="ledger-row-main" onClick={() => expandable && setOpen(!open)} aria-expanded={expandable ? open : undefined} disabled={!expandable}>
        <StateMark state={shown} />
        <span className="ledger-agent">
          <span className="ledger-agent-name">{agent.label}{runs.length > 1 && <span className="ledger-count">{runs.length} runs</span>}</span>
          <span className="ledger-agent-summary">{plainSummary(latest?.summary?.split("\n")[0]) || agent.does}</span>
        </span>
        <span className="ledger-side">
          {notApplicable ? <span className="ledger-state-text">Not applicable</span> : conf !== null && state === "done" ? (
            <span className="conf" title={`Average confidence ${(conf * 100).toFixed(0)}%`}>
              <span className="conf-bar"><span style={{ width: `${Math.round(conf * 100)}%` }} /></span>
              <span className="conf-num">{Math.round(conf * 100)}%</span>
            </span>
          ) : <span className="ledger-state-text">{STATE_TEXT[state]}</span>}
          {issues.length > 0 && <span className="issue-count" title={`${issues.length} issue(s)`}><AlertTriangle size={12} /> {issues.length}</span>}
          {expandable && <ChevronRight size={16} className={`chev ${open ? "chev-open" : ""}`} />}
        </span>
      </button>
      {open && (
        <div className="ledger-detail">
          {runs.map((r) => (
            <div key={r.id} className="ledger-run">
              <div className="ledger-run-head">
                <span>{formatClock(r.created_at)}</span>
                <span className={`run-status run-${r.status}`}>{r.status.replace("_", " ")}</span>
                {r.confidence !== null && <span>confidence {Math.round((r.confidence ?? 0) * 100)}%</span>}
              </div>
              {r.summary && <p className="ledger-run-summary">{r.summary}</p>}
              {(r.issues ?? []).map((iss, k) => (
                <div key={k} className={`issue issue-${iss.severity ?? "warn"}`}>
                  <AlertTriangle size={13} /> <span>{iss.message || iss.code}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </li>
  );
}
