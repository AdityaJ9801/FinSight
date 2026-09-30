import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../lib/api";
import { refreshResults } from "../lib/hooks";
import type { Job } from "../lib/types";
import { useFeedback } from "./feedback";
import { FilePicker } from "./FilePicker";
import { Spinner } from "./ui";

export function AddStatementsDialog({ job, onClose, onAdded }: { job: Job; onClose: () => void; onAdded: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const qc = useQueryClient();
  const { toast } = useFeedback();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const add = useMutation({
    mutationFn: () => api.addDocuments(job.id, files),
    onSuccess: (res) => {
      const skipped = res.skipped.length ? ` Skipped ${res.skipped.join(", ")}: already part of this analysis.` : "";
      toast(`Added ${res.added.length} statement${res.added.length === 1 ? "" : "s"}. Re-running the analysis.${skipped}`, "success");
      refreshResults(qc, job.id);
      qc.invalidateQueries({ queryKey: ["job", job.id] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      onAdded();
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const count = job.documents?.length ?? 0;

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="add-title"
        onSubmit={(e) => { e.preventDefault(); if (files.length) add.mutate(); }}>
        <div className="dialog-head">
          <h2 id="add-title">Add statements</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <p>
          The analysis re-runs on all {count + files.length || "the"} statements together, so ratios, checks and the report
          reflect the complete set. Current results stay saved as the previous version.
        </p>
        <div className="dialog-body"><FilePicker id="add-file-input" files={files} onChange={setFiles} /></div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!files.length || add.isPending}>
            {add.isPending ? <><Spinner /> Uploading…</> : files.length > 1 ? `Add ${files.length} statements and re-run` : "Add and re-run"}
          </button>
        </div>
      </form>
    </div>
  );
}
