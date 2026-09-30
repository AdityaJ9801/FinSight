import type { ReactNode } from "react";
import { statusInfo, type Tone } from "../lib/pipeline";
import type { JobStatus } from "../lib/types";

export function StatusBadge({ status }: { status: JobStatus | undefined }) {
  const { label, tone } = statusInfo(status);
  return <span className={`status status-${tone}`}><StatusDot tone={tone} />{label}</span>;
}

export function StatusDot({ tone }: { tone: Tone }) {
  return <span className={`dot dot-${tone}`} aria-hidden="true" />;
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />;
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="error-note" role="alert">{msg}</div>;
}

export function Skeleton({ h = 16, w = "100%" }: { h?: number; w?: number | string }) {
  return <span className="skeleton" style={{ height: h, width: w }} />;
}

/** Minimal trend line over a metric's periods. Draws nothing for fewer than two points. */
export function Sparkline({ values, good }: { values: number[]; good: boolean | null }) {
  if (values.length < 2) return <span className="spark-empty">—</span>;
  const w = 72, h = 22, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [
    pad + (i * (w - pad * 2)) / (values.length - 1),
    h - pad - ((v - min) / span) * (h - pad * 2),
  ]);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  const cls = good === null ? "spark-flat" : good ? "spark-good" : "spark-bad";
  return (
    <svg className={`spark ${cls}`} width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={d} fill="none" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r="2.2" />
    </svg>
  );
}

export function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#1D3049" />
      <path d="M9 22V10h10M9 16h7" stroke="#E9E4D4" strokeWidth="2.6" strokeLinecap="round" fill="none" />
      <circle cx="22.5" cy="21.5" r="2.5" fill="#34A676" />
    </svg>
  );
}
