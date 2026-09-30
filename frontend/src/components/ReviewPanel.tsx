import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
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

  const acceptAll = useMutation({
    mutationFn: async () => {
      let remaining = 0;
      for (const item of recon) remaining = (await api.resolveReview(item.id, { note: "Accepted by reviewer" })).remaining_open;
      return remaining;
    },
    onSuccess: (remaining) => {
      toast(remaining === 0 ? "Accepted. The analysis is continuing." : `Accepted. ${remaining} item(s) still need attention.`, "success");
      refresh();
    },
    onError: (e: Error) => { toast(e.message, "error"); refresh(); },
  });

  if (!recon.length && !mapping.length) return null;
  const noFacts = recon.some((i) => i.payload.check_code === "NO_FACTS");

  return (
    <section className="review" aria-labelledby="review-title">
      <div className="review-head">
        <h2 id="review-title">
          {noFacts ? "No financial figures could be read" : recon.length ? "The statements don't tie out" : "Check these account mappings"}
        </h2>
        <p>
          {noFacts
            ? "None of the uploaded files produced balance sheet or P&L line items. Start a new analysis that includes a balance sheet or P&L; continuing without them will stop again at this check."
            : recon.length
              ? "A reconciliation check found a difference. Read each explanation. If the difference is expected, accept it and the analysis will continue."
              : "These line items were mapped with low confidence. They were accepted automatically; correct any that are wrong."}
        </p>
      </div>

      {recon.length > 0 && (
        <>
          <div className="recon-list">
            {recon.map((item) => (
              <article key={item.id} className="recon">
                <h3>{humanize(item.payload.check_code ?? "Reconciliation check")}</h3>
                <dl className="recon-figures">
                  <div><dt>Expected</dt><dd>{formatNumber(item.payload.expected)}</dd></div>
                  <div><dt>Found</dt><dd>{formatNumber(item.payload.actual)}</dd></div>
                  <div><dt>Difference</dt><dd className="neg">{formatNumber(item.payload.diff)}</dd></div>
                </dl>
                {item.payload.explanation && <p>{item.payload.explanation}</p>}
              </article>
            ))}
          </div>
          <div className="review-actions">
            {noFacts && <Link to="/" className="btn btn-primary">Start a new analysis</Link>}
            <button className={`btn ${noFacts ? "btn-secondary" : "btn-primary"}`} onClick={() => acceptAll.mutate()} disabled={acceptAll.isPending}>
              {acceptAll.isPending ? <><Spinner /> Accepting…</> : recon.length > 1 ? `Accept ${recon.length} differences and continue` : "Accept difference and continue"}
            </button>
          </div>
        </>
      )}

      {mapping.length > 0 && (
        <details className="mapping" open={!recon.length}>
          <summary>{mapping.length} low-confidence account mapping{mapping.length > 1 ? "s" : ""}</summary>
          <table className="table">
            <thead><tr><th>Line item</th><th>Mapped to</th><th className="num">Confidence</th><th>Correct account</th></tr></thead>
            <tbody>{mapping.map((m) => <MappingRow key={m.id} item={m} onDone={refresh} />)}</tbody>
          </table>
        </details>
      )}
    </section>
  );
}

function MappingRow({ item, onDone }: { item: ReviewItem; onDone: () => void }) {
  const [account, setAccount] = useState("");
  const { toast } = useFeedback();
  const fix = useMutation({
    mutationFn: () => api.resolveReview(item.id, { account_id: account.trim() }),
    onSuccess: () => { toast(`Remapped “${item.payload.label}” to ${account.trim()}.`, "success"); onDone(); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  return (
    <tr>
      <td>{item.payload.label}</td>
      <td className="code">{item.payload.suggested_account_id}</td>
      <td className="num">{item.payload.confidence !== undefined ? `${Math.round(item.payload.confidence * 100)}%` : "—"}</td>
      <td>
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); if (account.trim()) fix.mutate(); }}>
          <input value={account} onChange={(e) => setAccount(e.target.value)} placeholder="e.g. BS.CA.INVENTORY" aria-label={`Correct account for ${item.payload.label}`} />
          <button className="btn btn-secondary btn-sm" disabled={!account.trim() || fix.isPending}>Save</button>
        </form>
      </td>
    </tr>
  );
}
