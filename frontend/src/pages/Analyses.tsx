import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { useJobs } from "../lib/hooks";
import { TEMPLATES } from "../lib/pipeline";
import { formatRelative } from "../lib/format";
import { EmptyState, ErrorNote, Skeleton, StatusBadge } from "../components/ui";
import { useFeedback } from "../components/feedback";

export function AnalysesPage() {
  const { data, isLoading, error } = useJobs();
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { confirm, toast } = useFeedback();

  const del = useMutation({
    mutationFn: api.deleteJob,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); toast("Analysis deleted.", "success"); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (data ?? []).filter((j) => !term || j.goal.toLowerCase().includes(term)
      || (j.company_name ?? "").toLowerCase().includes(term) || j.id.includes(term));
  }, [data, q]);

  const onDelete = async (id: string, goal: string) => {
    const ok = await confirm({
      title: "Delete this analysis?",
      body: `“${goal}” and everything generated from it (extracted data, metrics, findings, charts and reports) will be permanently removed.`,
      confirmLabel: "Delete analysis",
      danger: true,
    });
    if (ok) del.mutate(id);
  };

  return (
    <div className="page">
      <header className="page-head page-head-row">
        <div>
          <h1>Analyses</h1>
          <p className="lede">Every analysis run on this workspace, newest first.</p>
        </div>
        <Link to="/" className="btn btn-primary">New analysis</Link>
      </header>

      {error ? <ErrorNote error={error} /> : isLoading ? (
        <div className="stack">{[0, 1, 2].map((i) => <Skeleton key={i} h={48} />)}</div>
      ) : !data?.length ? (
        <EmptyState title="No analyses yet" action={<Link to="/" className="btn btn-primary">Start your first analysis</Link>}>
          Upload a balance sheet, P&amp;L or bank statement to get a reconciled, verified report.
        </EmptyState>
      ) : (
        <>
          <div className="search">
            <Search size={16} />
            <input type="search" placeholder="Search by company, title or ID" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search analyses" />
          </div>
          <div className="table-card">
            <table className="table table-rows">
              <thead>
                <tr><th>Analysis</th><th>Status</th><th className="num">Documents</th><th>Started</th><th aria-label="Actions" /></tr>
              </thead>
              <tbody>
                {rows.map((j) => (
                  <tr key={j.id} onClick={() => navigate(`/analyses/${j.id}`)} className="row-link">
                    <td>
                      <Link to={`/analyses/${j.id}`} className="row-title" onClick={(e) => e.stopPropagation()}>{j.company_name || j.goal || "Untitled analysis"}</Link>
                      <div className="row-sub">{j.company_name ? `${j.goal}. ` : ""}{TEMPLATES[j.plan_template]?.label ?? j.plan_template}</div>
                    </td>
                    <td><StatusBadge status={j.status} /></td>
                    <td className="num">{j.document_count ?? "—"}</td>
                    <td className="muted nowrap">{formatRelative(j.created_at)}</td>
                    <td className="actions">
                      <button className="icon-btn" aria-label={`Delete ${j.goal}`} title="Delete"
                        onClick={(e) => { e.stopPropagation(); onDelete(j.id, j.goal); }}><Trash2 size={16} /></button>
                    </td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={5} className="muted center">No analyses match “{q}”.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
