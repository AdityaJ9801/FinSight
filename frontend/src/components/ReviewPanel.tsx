import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, ShieldCheck, RefreshCw, Check } from "lucide-react";
import { api } from "../lib/api";
import { formatNumber, humanize } from "../lib/format";
import type { Job, ReviewItem } from "../lib/types";
import { useFeedback } from "./feedback";
import { Spinner } from "./ui";

export function ReviewPanel({ job, items }: { job: Job; items: ReviewItem[] }) {
  const qc = useQueryClient();
  const { toast } = useFeedback();
  const recon = items.filter((i) => i.kind === "reconciliation");
  const mapping = items.filter((i) => i.kind === "mapping");

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["review", job.id] });
    qc.invalidateQueries({ queryKey: ["job", job.id] });
    qc.invalidateQueries({ queryKey: ["jobs"] });
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

  if (!recon.length && !mapping.length) return null;
  const noFacts = recon.some((i) => i.payload.check_code === "NO_FACTS");

  return (
    <section className="review" aria-labelledby="review-title">
      <div className="review-head">
        <h2 id="review-title">
          {noFacts
            ? "No financial figures could be read"
            : recon.length
            ? "Verification Review Required"
            : "Review Account Mappings"}
        </h2>
        <p>
          {noFacts
            ? "None of the uploaded files produced balance sheet or P&L line items. Start a new analysis with a standard financial statement."
            : recon.length
            ? "The Verification Advisor has diagnosed the discrepancies and generated recommendations. You can accept AI recommendations with 1 click without manually entering figures."
            : "The Verification Advisor has verified account mappings. Review suggestions below or apply all recommendations."}
        </p>
      </div>

      {/* Verification Advisor Quick-Action Banner */}
      <div className="advisor-banner">
        <div className="advisor-title">
          <Sparkles size={16} />
          <span>Verification Advisor: Smart Recommendations Active</span>
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
            onClick={() => autoResolveAll.mutate()}
            disabled={autoResolveAll.isPending || noFacts}
            title="Automatically apply all recommended accounts and audit resolutions without manual input"
          >
            {autoResolveAll.isPending ? (
              <>
                <Spinner /> Applying AI Recommendations…
              </>
            ) : (
              <>
                <Sparkles size={13} /> Apply All AI Recommendations & Resume
              </>
            )}
          </button>
        </div>
      </div>

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
        <details className="mapping" open={!recon.length}>
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
