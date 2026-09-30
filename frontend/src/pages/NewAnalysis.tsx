import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useIndustries } from "../lib/hooks";
import { agentsFor, STAGE_LABEL, TEMPLATES, type Stage } from "../lib/pipeline";
import { useFeedback } from "../components/feedback";
import { FilePicker } from "../components/FilePicker";
import { Spinner } from "../components/ui";

const SAMPLES = ["balance_sheet.csv", "pnl.csv", "cash_flow.csv"];

export function NewAnalysisPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [goal, setGoal] = useState("");
  const [company, setCompany] = useState("");
  const [industry, setIndustry] = useState("");
  const [template, setTemplate] = useState("full_analysis");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { toast } = useFeedback();
  const industries = useIndustries();

  // Chosen files live only in this page's memory; warn before a reload or tab close loses them.
  useEffect(() => {
    if (!files.length) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [files.length]);

  const loadSamples = async () => {
    try {
      const loaded = await Promise.all(SAMPLES.map(async (name) => {
        const resp = await fetch(`/samples/${name}`);
        if (!resp.ok) throw new Error(name);
        return new File([await resp.blob()], name, { type: "text/csv" });
      }));
      const names = new Set(files.map((f) => f.name));
      setFiles([...files, ...loaded.filter((f) => !names.has(f.name))]);
      if (!goal) setGoal("FY24 review ahead of a working-capital facility renewal");
      if (!company) setCompany("Sample Manufacturing Pvt Ltd");
      if (!industry) setIndustry("manufacturing");
    } catch {
      toast("Couldn't load the sample statements.", "error");
    }
  };

  const run = useMutation({
    mutationFn: () => api.createJob(files, {
      goal: goal.trim() || (company.trim() ? `${company.trim()}: ${TEMPLATES[template].label.toLowerCase()}` : TEMPLATES[template].label),
      planTemplate: template, companyName: company.trim(), industry,
    }),
    onSuccess: ({ job_id }) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      navigate(`/analyses/${job_id}`);
    },
    onError: (err: ApiError & { jobId?: string }) => {
      toast(err.message, "error");
      if (err.jobId) { qc.invalidateQueries({ queryKey: ["jobs"] }); navigate(`/analyses/${err.jobId}`); }
    },
  });

  const agents = agentsFor(template);
  const stages: Stage[] = ["data", "analysis", "delivery"];

  return (
    <div className="page">
      <header className="page-head">
        <h1>New analysis</h1>
        <p className="lede">Upload a company's financial statements. FinSight reads them, reconciles the numbers, analyses them and writes a verified report you can question.</p>
      </header>

      <div className="compose">
        <form className="compose-form" onSubmit={(e) => { e.preventDefault(); if (files.length) run.mutate(); }}>
          <section className="field-group">
            <div className="field-head">
              <label className="field-label" htmlFor="file-input">Statements</label>
              <button type="button" className="link-btn" onClick={loadSamples}>Use sample statements</button>
            </div>
            <FilePicker files={files} onChange={setFiles} />
          </section>

          <div className="field-row">
            <div className="field-group">
              <label className="field-label" htmlFor="company">Company</label>
              <input id="company" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="e.g. Sharma Auto Components Pvt Ltd…" autoComplete="organization" name="company" />
            </div>
            <div className="field-group">
              <label className="field-label" htmlFor="industry">Industry</label>
              <select id="industry" value={industry} onChange={(e) => setIndustry(e.target.value)}>
                <option value="">Not set</option>
                {industries.data?.industries.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
              </select>
            </div>
          </div>
          <div className="field-note field-note-tight">The industry sets which peers the ratios are benchmarked against. You can change it later.</div>

          <section className="field-group">
            <label className="field-label" htmlFor="goal">What should the analysis focus on?</label>
            <textarea id="goal" rows={2} value={goal} onChange={(e) => setGoal(e.target.value)}
              name="goal" autoComplete="off"
              placeholder="e.g. Assess FY24 performance and working-capital pressure ahead of a term-loan renewal…" />
            <div className="field-note">Optional. It becomes the analysis title and steers what the report emphasises.</div>
          </section>

          <fieldset className="field-group">
            <legend className="field-label">Analysis type</legend>
            <div className="choice-list">
              {Object.entries(TEMPLATES).map(([key, t]) => (
                <label key={key} className={`choice ${template === key ? "choice-on" : ""}`}>
                  <input type="radio" name="template" value={key} checked={template === key} onChange={() => setTemplate(key)} />
                  <span className="choice-body">
                    <span className="choice-title">{t.label}</span>
                    <span className="choice-desc">{t.blurb}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="compose-actions">
            <button type="submit" className="btn btn-primary btn-lg" disabled={!files.length || run.isPending}>
              {run.isPending ? <><Spinner /> Uploading…</> : "Start analysis"}
            </button>
            {!files.length && <span className="field-note">Add at least one statement to start.</span>}
          </div>
        </form>

        <aside className="plan-preview" aria-label="What happens next">
          <h2>What happens next</h2>
          <ol className="plan-steps">
            {stages.map((s, si) => (
              <li key={s}>
                <span className="plan-step">{si + 1}</span>
                <div>
                  <div className="plan-stage-name">{STAGE_LABEL[s]}</div>
                  <div className="plan-does">{agents.filter((a) => a.stage === s).map((a) => a.label).join(", ")}</div>
                </div>
              </li>
            ))}
          </ol>
          <p className="plan-note">
            If a check doesn't tie out, the analysis pauses and asks you before continuing. You can add guidance while it
            runs, and ask questions or add more statements once it finishes.
          </p>
        </aside>
      </div>
    </div>
  );
}
