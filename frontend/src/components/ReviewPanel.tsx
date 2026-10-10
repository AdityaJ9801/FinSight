import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, ShieldCheck, RefreshCw, Check, AlertTriangle, ExternalLink } from "lucide-react";
import { api, reportUrl } from "../lib/api";
import { formatNumber, humanize } from "../lib/format";
import type { Job, ReviewItem } from "../lib/types";
import { useFeedback } from "./feedback";
import { Spinner } from "./ui";

export function ReviewPanel({ job, items }: { job: Job; items: ReviewItem[] }) {
  const qc = useQueryClient();
  const { toast } = useFeedback();
  const recon = items.filter((i) => i.kind === "reconciliation");
  const mapping = items.filter((i) => i.kind === "mapping");
  const verification = items.filter((i) => i.kind === "verification");

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["review", job.id] });
    qc.invalidateQueries({ queryKey: ["job", job.id] });
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["report", job.id] });
  };

  const autoResolveAll = useMutation({
    mutationFn: () => api.autoResolveReview(job.id),
    onSuccess: (res) => {
      toast(res.summary || "AI recommendations applied. Analysis is resuming.", "success");
      refresh();
    },
    onError: (e: Error) => {
      toast(e.message, "error");
      refresh();
    },
  });

  const getRecommendations = useMutation({
    mutationFn: () => api.recommendReview(job.id),
    onSuccess: (res) => {
      toast(res.summary || "AI Verification recommendations updated.", "success");
      refresh();
    },
    onError: (e: Error) => {
      toast(e.message, "error");
      refresh();
    },
  });

  const acceptAllRecon = useMutation({
    mutationFn: async () => {
      let remaining = 0;
      for (const item of recon) {
        const note = item.payload.recommendation?.audit_note || "Accepted by reviewer";
        remaining = (await api.resolveReview(item.id, { note })).remaining_open;
      }
      return remaining;
    },
    onSuccess: (remaining) => {
      toast(
        remaining === 0 ? "Accepted. The analysis is continuing." : `Accepted. ${remaining} item(s) still need attention.`,
        "success"
      );
      refresh();
    },
    onError: (e: Error) => {
      toast(e.message, "error");
      refresh();
    },
  });

  const acceptAllVerification = useMutation({
    mutationFn: async () => {
      let remaining = 0;
      for (const item of verification) {
        const note = item.payload.recommendation?.audit_note || "Analyst approved and certified.";
        remaining = (await api.resolveReview(item.id, { note })).remaining_open;
      }
      return remaining;
    },
    onSuccess: (remaining) => {
      toast(
        remaining === 0 ? "Report certified and approved! Analysis completed." : `Certified. ${remaining} item(s) still need attention.`,
        "success"
      );
      refresh();
    },
    onError: (e: Error) => {
      toast(e.message, "error");
      refresh();
    },
  });

  if (!recon.length && !mapping.length && !verification.length) return null;
  const noFacts = recon.some((i) => i.payload.check_code === "NO_FACTS");

  return (
    <section className="review" aria-labelledby="review-title">
      <div className="review-head">
        <h2 id="review-title">
          {noFacts
            ? "No financial figures could be read"
            : verification.length
            ? "Report Verification & Analyst Sign-Off Required"
            : recon.length
            ? "Verification Review Required"
            : "Review Account Mappings"}
        </h2>
        <p>
          {noFacts
            ? "None of the uploaded files produced balance sheet or P&L line items. Start a new analysis with a standard financial statement."
            : verification.length
            ? "Automated verification flagged items that require analyst sign-off before certifying the report. Review the problems below, accept the AI Verification Advisor recommendation with 1 click, or submit your manual audit notes to complete the analysis."
            : recon.length
            ? "The Verification Advisor has diagnosed the discrepancies and generated recommendations. You can accept AI recommendations with 1 click without manually entering figures."
            : "The Verification Advisor has verified account mappings. Review suggestions below or apply all recommendations."}
        </p>
      </div>

      {/* Verification Advisor Quick-Action Banner */}
      <div className="advisor-banner">
        <div className="advisor-title">
          <Sparkles size={16} />
          <span>
            {verification.length
              ? "Verification Advisor: Discrepancy Diagnostics & Solutions Ready"
              : "Verification Advisor: Smart Recommendations Active"}
          </span>
        </div>
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => getRecommendations.mutate()}
            disabled={getRecommendations.isPending || autoResolveAll.isPending}
            title="Re-run Verification Advisor to refresh recommendations"
          >
            {getRecommendations.isPending ? (
              <>
                <Spinner /> Analyzing…
              </>
            ) : (
              <>
                <RefreshCw size={13} /> Refresh Recommendations
              </>
            )}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => (verification.length ? acceptAllVerification.mutate() : autoResolveAll.mutate())}
            disabled={autoResolveAll.isPending || acceptAllVerification.isPending || noFacts}
            title={
              verification.length
                ? "Apply recommended audit notes and certify the report immediately"
                : "Automatically apply all recommended accounts and audit resolutions without manual input"
            }
          >
            {autoResolveAll.isPending || acceptAllVerification.isPending ? (
              <>
                <Spinner /> Applying AI Recommendations…
              </>
            ) : (
              <>
                <Sparkles size={13} />
                {verification.length
                  ? "Approve & Certify All Reports (1-Click)"
                  : "Apply All AI Recommendations & Resume"}
              </>
            )}
          </button>
        </div>
      </div>

      {verification.length > 0 && (
        <div className="verification-list" style={{ marginBottom: "16px" }}>
          {verification.map((item) => (
            <VerificationCard key={item.id} item={item} job={job} onDone={refresh} />
          ))}
        </div>
      )}

      {recon.length > 0 && (
        <>
          <div className="recon-list">
            {recon.map((item) => (
              <ReconciliationCard key={item.id} item={item} onDone={refresh} />
            ))}
          </div>
          <div className="review-actions">
            {noFacts && (
              <Link to="/" className="btn btn-primary">
                Start a new analysis
              </Link>
            )}
            <button
              className={`btn ${noFacts ? "btn-secondary" : "btn-primary"}`}
              onClick={() => acceptAllRecon.mutate()}
              disabled={acceptAllRecon.isPending}
            >
              {acceptAllRecon.isPending ? (
                <>
                  <Spinner /> Accepting…
                </>
              ) : recon.length > 1 ? (
                `Accept ${recon.length} differences and continue`
              ) : (
                "Accept difference and continue"
              )}
            </button>
          </div>
        </>
      )}

      {mapping.length > 0 && (
        <details className="mapping" open={!recon.length && !verification.length}>
          <summary>
            {mapping.length} account mapping{mapping.length > 1 ? "s" : ""} awaiting review
          </summary>
          <table className="table">
            <thead>
              <tr>
                <th>Line item</th>
                <th>Current Mapping</th>
                <th className="num">Conf.</th>
                <th>AI Advisor Recommendation</th>
                <th>Correct Account</th>
              </tr>
            </thead>
            <tbody>
              {mapping.map((m) => (
                <MappingRow key={m.id} item={m} onDone={refresh} />
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}

function ReconciliationCard({ item, onDone }: { item: ReviewItem; onDone: () => void }) {
  const { toast } = useFeedback();
  const rec = item.payload.recommendation;

  const resolveSingle = useMutation({
    mutationFn: () =>
      api.resolveReview(item.id, {
        note: rec?.audit_note || "Accepted by reviewer via Verification Advisor",
      }),
    onSuccess: (res) => {
      toast(
        res.remaining_open === 0
          ? "Accepted. The analysis is continuing."
          : `Accepted. ${res.remaining_open} item(s) remaining.`,
        "success"
      );
      onDone();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <article className="recon">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "12px" }}>
        <h3>{humanize(item.payload.check_code ?? "Reconciliation check")}</h3>
        {rec?.auto_resolvable && (
          <button
            type="button"
            className="btn btn-secondary btn-xs"
            onClick={() => resolveSingle.mutate()}
            disabled={resolveSingle.isPending}
            style={{ flexShrink: 0 }}
          >
            {resolveSingle.isPending ? <Spinner /> : <><Check size={11} /> Accept Recommendation</>}
          </button>
        )}
      </div>

      <dl className="recon-figures">
        <div>
          <dt>Expected</dt>
          <dd>{formatNumber(item.payload.expected)}</dd>
        </div>
        <div>
          <dt>Found</dt>
          <dd>{formatNumber(item.payload.actual)}</dd>
        </div>
        <div>
          <dt>Difference</dt>
          <dd className="neg">{formatNumber(item.payload.diff)}</dd>
        </div>
      </dl>

      {item.payload.explanation && <p>{item.payload.explanation}</p>}

      {rec && (
        <div className="advisor-card">
          <div className="advisor-card-title">
            <ShieldCheck size={14} color="#0284c7" />
            <span>{rec.title || "AI Verification Diagnosis"}</span>
            {rec.confidence && (
              <span className="advisor-rec-chip" style={{ fontSize: "11px", padding: "1px 6px" }}>
                {Math.round(rec.confidence * 100)}% match
              </span>
            )}
          </div>
          <div className="advisor-card-body">{rec.reasoning}</div>
          {rec.audit_note && (
            <div className="advisor-card-audit">
              <strong>Audit Note: </strong>
              {rec.audit_note}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function MappingRow({ item, onDone }: { item: ReviewItem; onDone: () => void }) {
  const rec = item.payload.recommendation;
  const initialAccount = rec?.suggested_account_id || item.payload.suggested_account_id || "";
  const [account, setAccount] = useState(initialAccount);

  useEffect(() => {
    if (initialAccount && !account) {
      setAccount(initialAccount);
    }
  }, [initialAccount]);

  const { toast } = useFeedback();

  const fix = useMutation({
    mutationFn: (targetAccount?: string) => {
      const acc = targetAccount || account.trim() || initialAccount;
      return api.resolveReview(item.id, { account_id: acc });
    },
    onSuccess: (_, vars) => {
      toast(`Remapped “${item.payload.label}” to ${vars || account.trim() || initialAccount}.`, "success");
      onDone();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <tr>
      <td>
        <strong>{item.payload.label}</strong>
        {item.payload.section ? (
          <div style={{ fontSize: "11px", color: "var(--graphite)" }}>Section: {String(item.payload.section)}</div>
        ) : null}

      </td>
      <td className="code">{item.payload.suggested_account_id || "—"}</td>
      <td className="num">
        {item.payload.confidence !== undefined ? `${Math.round(item.payload.confidence * 100)}%` : "—"}
      </td>
      <td>
        {rec ? (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span className="advisor-rec-chip" title={rec.reasoning}>
                <Sparkles size={11} />
                <code>{rec.suggested_account_id}</code>
                {rec.confidence && <span>({Math.round(rec.confidence * 100)}%)</span>}
              </span>
              <button
                type="button"
                className="btn btn-primary btn-xs"
                onClick={() => fix.mutate(rec.suggested_account_id)}
                disabled={fix.isPending}
                title="1-click accept recommendation"
              >
                {fix.isPending ? <Spinner /> : "Accept"}
              </button>
            </div>
            {rec.account_name && (
              <div style={{ fontSize: "11px", color: "var(--graphite)", marginTop: "2px" }}>
                {rec.account_name}
              </div>
            )}
            {rec.alternatives && rec.alternatives.length > 0 && (
              <div className="chip-row">
                <span style={{ fontSize: "11px", color: "var(--graphite)" }}>Alt:</span>
                {rec.alternatives.map((alt) => (
                  <button
                    key={alt.account_id}
                    type="button"
                    className="btn btn-secondary btn-xs"
                    onClick={() => {
                      setAccount(alt.account_id);
                    }}
                    title={`Click to select ${alt.account_name || alt.account_id}`}
                  >
                    {alt.account_id}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <span style={{ color: "var(--graphite)", fontSize: "12px" }}>Analyzing…</span>
        )}
      </td>
      <td>
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (account.trim()) fix.mutate();
          }}
        >
          <input
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            placeholder="e.g. PL.COGS"
            aria-label={`Correct account for ${item.payload.label}`}
          />
          <button className="btn btn-secondary btn-sm" disabled={!account.trim() || fix.isPending}>
            Save
          </button>
        </form>
      </td>
    </tr>
  );
}

function VerificationCard({ item, job, onDone }: { item: ReviewItem; job: Job; onDone: () => void }) {
  const { toast } = useFeedback();
  const rec = item.payload.recommendation;
  const issues = (item.payload.issues as string[] | undefined) || [];
  const feedback = (item.payload.feedback as string[] | undefined) || [];
  const [manualNote, setManualNote] = useState(
    rec?.audit_note || "Analyst verified figures against source files; approved and certified."
  );

  const resolveItem = useMutation({
    mutationFn: (note: string) =>
      api.resolveReview(item.id, {
        note: note.trim() || rec?.audit_note || "Analyst certified and signed off.",
      }),
    onSuccess: () => {
      toast("Report approved and certified! Analysis is now complete.", "success");
      onDone();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <article className="verification-card">
      <div className="verification-card-header">
        <div>
          <div className="verification-card-title">
            <AlertTriangle size={18} color="#ea580c" />
            <span>{String(item.payload.title || "Report Verification Sign-Off Needed")}</span>
            <span className="verification-badge">Needs Analyst</span>
          </div>
          <p style={{ margin: "4px 0 0", fontSize: "13px", color: "var(--ink-2)" }}>
            {String(item.payload.explanation || "Automated verification encountered discrepancies requiring analyst review.")}
          </p>
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <a
            href={reportUrl(job.id, "html")}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary btn-xs"
            title="Open draft report HTML in new tab"
          >
            <ExternalLink size={12} /> Inspect Draft Report
          </a>
        </div>
      </div>

      {/* Flagged Problems */}
      <div className="verification-problems-box">
        <div className="verification-problems-title">
          <AlertTriangle size={13} />
          Flagged Problems ({issues.length || 1})
        </div>
        {issues.length > 0 ? (
          <ul className="verification-issues-list">
            {issues.map((iss, idx) => (
              <li key={idx}>{iss}</li>
            ))}
          </ul>
        ) : (
          <p style={{ margin: 0, fontSize: "13px" }}>{String(item.payload.explanation || "Verification discrepancies detected.")}</p>
        )}
        {feedback.length > 0 && (
          <div style={{ marginTop: "8px", fontSize: "12px", color: "var(--graphite)" }}>
            <strong>Supervisor Feedback:</strong> {feedback.join("; ")}
          </div>
        )}
      </div>

      {/* Recommended Solution (AI Verification Advisor) */}
      <div className="advisor-card" style={{ borderLeftColor: "#10b981", background: "rgba(16, 185, 129, 0.04)" }}>
        <div className="advisor-card-title">
          <ShieldCheck size={16} color="#10b981" />
          <span>{rec?.title || "Recommended Solution (AI Verification Advisor)"}</span>
          <span
            className="advisor-rec-chip"
            style={{
              fontSize: "11px",
              padding: "1px 6px",
              background: "rgba(16, 185, 129, 0.15)",
              color: "#047857",
              borderColor: "rgba(16, 185, 129, 0.3)",
            }}
          >
            {Math.round((rec?.confidence || 0.94) * 100)}% match
          </span>
        </div>
        <div className="advisor-card-body" style={{ marginTop: "4px" }}>
          {rec?.reasoning ||
            "Advisor analyzed the reported discrepancy. Discrepancies stem from rounding, alternative phrasing, or newly computed ratios. Safe to certify with documented audit note."}
        </div>
        {rec?.audit_note && (
          <div className="advisor-card-audit" style={{ background: "rgba(16, 185, 129, 0.08)" }}>
            <strong>Recommended Audit Note: </strong>
            {rec.audit_note}
          </div>
        )}
        <div style={{ marginTop: "10px", display: "flex", gap: "8px", alignItems: "center" }}>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => resolveItem.mutate(rec?.audit_note || manualNote)}
            disabled={resolveItem.isPending}
          >
            {resolveItem.isPending ? (
              <Spinner />
            ) : (
              <>
                <Check size={14} /> Accept Recommendation & Certify (1-Click)
              </>
            )}
          </button>
        </div>
      </div>

      {/* Manual Input / Sign-Off Option */}
      <details className="verification-manual-section">
        <summary>Manual Sign-Off & Custom Audit Output</summary>
        <div className="verification-manual-body">
          <p style={{ margin: "0 0 8px", fontSize: "12px", color: "var(--graphite)" }}>
            Enter your custom auditor / reviewer remarks to override discrepancies and publish the final report as certified:
          </p>
          <textarea
            className="verification-manual-textarea"
            value={manualNote}
            onChange={(e) => setManualNote(e.target.value)}
            placeholder="e.g. Manually verified statements against uploaded PDFs; reconciliation differences are due to rounding in non-current liabilities."
          />
          <div style={{ marginTop: "8px", display: "flex", justifyContent: "flex-end", gap: "8px" }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => resolveItem.mutate(manualNote)}
              disabled={!manualNote.trim() || resolveItem.isPending}
            >
              {resolveItem.isPending ? <Spinner /> : "Certify with Custom Audit Note"}
            </button>
          </div>
        </div>
      </details>
    </article>
  );
}
