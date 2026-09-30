import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Columns2, FilePlus2, Library, Menu, Settings, X } from "lucide-react";
import { useAgentRegistry, useJobs, useLlmStatus } from "../lib/hooks";
import { statusInfo } from "../lib/pipeline";
import { Logo, StatusDot } from "./ui";

export function Shell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  useAgentRegistry(); // labels any backend agent the UI doesn't know by name

  return (
    <div className="shell">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="topbar">
        <button className="icon-btn icon-btn-light" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={20} /></button>
        <span className="wordmark"><Logo /> FinSight</span>
      </header>
      <nav className={`rail ${open ? "rail-open" : ""}`} aria-label="Main">
        <div className="rail-head">
          <NavLink to="/" className="wordmark"><Logo /> FinSight</NavLink>
          <button className="icon-btn icon-btn-light rail-close" aria-label="Close navigation" onClick={() => setOpen(false)}><X size={18} /></button>
        </div>
        <NavLink to="/" end className="rail-link"><FilePlus2 size={17} /> New analysis</NavLink>
        <NavLink to="/analyses" end className="rail-link"><Library size={17} /> Analyses</NavLink>
        <NavLink to="/compare" className="rail-link"><Columns2 size={17} /> Compare</NavLink>
        <RecentJobs />
        <div className="rail-foot">
          <NavLink to="/settings" className="rail-link"><Settings size={17} /> Model &amp; keys</NavLink>
          <ModelIndicator />
        </div>
      </nav>
      {open && <div className="rail-scrim" onClick={() => setOpen(false)} />}
      <main className="main" id="main" tabIndex={-1}><Outlet /></main>
    </div>
  );
}

/** "4m", "3h", "2d", "12 Mar": enough to tell two runs for the same company apart. */
function shortAge(iso: string | null): string {
  if (!iso) return "";
  const t = Date.parse(iso.endsWith("Z") ? iso : iso + "Z");
  const s = (Date.now() - t) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)}d`;
  return new Date(t).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function RecentJobs() {
  const { data } = useJobs();
  if (!data?.length) return null;
  return (
    <div className="rail-recent">
      <div className="rail-caption">Recent</div>
      {data.slice(0, 6).map((j) => (
        <NavLink key={j.id} to={`/analyses/${j.id}`} className="rail-job" title={`${j.goal} (${statusInfo(j.status).label})`}>
          <StatusDot tone={statusInfo(j.status).tone} />
          <span className="rail-job-name">{j.company_name || j.goal || "Untitled analysis"}</span>
          <span className="rail-job-when">{shortAge(j.created_at)}</span>
        </NavLink>
      ))}
    </div>
  );
}

function ModelIndicator() {
  const { data, isError } = useLlmStatus();
  let text = "Checking model…";
  let tone = "neutral";
  if (isError) { text = "API offline"; tone = "danger"; }
  else if (data) {
    if (data.resolved_backend === "fake") { text = "Offline mock model"; tone = "attention"; }
    else { text = data.active_model; tone = "success"; }
  }
  return (
    <NavLink to="/settings" className="model-chip" title="Language model used by the agents">
      <span className={`dot dot-${tone}`} /> {text}
    </NavLink>
  );
}
