import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";
import { api } from "../lib/api";
import { useLlmStatus } from "../lib/hooks";
import type { LlmStatus } from "../lib/types";
import { ErrorNote, Skeleton, Spinner } from "../components/ui";
import { useFeedback } from "../components/feedback";

const PROVIDERS: { value: string; label: string; model: (s: LlmStatus) => string; needs?: "openai" | "gemini" | "custom" }[] = [
  { value: "auto", label: "Automatic", model: () => "Uses whichever key is set: OpenAI, then Gemini, then the offline mock" },
  { value: "openai", label: "OpenAI", model: (s) => s.models?.openai_model ?? "gpt-4o-mini", needs: "openai" },
  { value: "openai_reasoning", label: "OpenAI, reasoning", model: (s) => s.models?.openai_reasoning_model ?? "gpt-4o", needs: "openai" },
  { value: "gemini", label: "Gemini", model: (s) => s.models?.gemini_model ?? "gemini-2.0-flash", needs: "gemini" },
  { value: "gemini_reasoning", label: "Gemini, reasoning", model: (s) => s.models?.gemini_reasoning_model ?? "gemini-1.5-pro", needs: "gemini" },
  { value: "real", label: "Custom endpoint", model: (s) => s.models?.custom_model ?? "Configured in .env", needs: "custom" },
  { value: "fake", label: "Offline mock", model: () => "No API calls. Deterministic answers for testing" },
];

export function SettingsPage() {
  const { data, isLoading, error } = useLlmStatus();
  const qc = useQueryClient();
  const { toast } = useFeedback();
  const [backend, setBackend] = useState("auto");
  const [parallel, setParallel] = useState(true);
  const [openai, setOpenai] = useState("");
  const [gemini, setGemini] = useState("");

  useEffect(() => {
    if (data) { setBackend(data.configured_backend); setParallel(data.parallel_calls); }
  }, [data]);

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = { backend, parallel_calls: parallel };
      if (openai.trim()) payload.openai_api_key = openai.trim();
      if (gemini.trim()) payload.gemini_api_key = gemini.trim();
      return api.saveLlm(payload);
    },
    onSuccess: (status) => {
      qc.setQueryData(["llm"], status);
      setOpenai(""); setGemini("");
      toast("Model settings saved.", "success");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const dirty = !!data && (backend !== data.configured_backend || parallel !== data.parallel_calls || !!openai.trim() || !!gemini.trim());

  return (
    <div className="page page-form">
      <header className="page-head">
        <h1>Model &amp; keys</h1>
        <p className="lede">Choose the language model the agents use. Keys are saved to the API server's <code>.env</code> file and never shown again in full.</p>
      </header>

      {error ? <ErrorNote error={error} /> : isLoading || !data ? <Skeleton h={320} /> : (
        <form className="settings" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <div className="current">
            <span className="muted small">Currently answering</span>
            <strong>{data.resolved_backend === "fake" ? "Offline mock" : data.active_model}</strong>
            {data.resolved_backend === "fake" && <span className="small attention-text">Add a key below to get real analysis.</span>}
          </div>

          <fieldset className="field-group">
            <legend className="field-label">Provider</legend>
            <div className="choice-list">
              {PROVIDERS.map((p) => {
                const missingKey = p.needs && !data.keys_configured[p.needs] && !(p.needs === "openai" && openai) && !(p.needs === "gemini" && gemini);
                return (
                  <label key={p.value} className={`choice ${backend === p.value ? "choice-on" : ""}`}>
                    <input type="radio" name="backend" value={p.value} checked={backend === p.value} onChange={() => setBackend(p.value)} />
                    <span className="choice-body">
                      <span className="choice-title">{p.label}{missingKey && <span className="tag">Needs key</span>}</span>
                      <span className="choice-desc">{p.model(data)}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <div className="field-group">
            <KeyField id="openai" label="OpenAI API key" placeholder="sk-proj-…" masked={data.masked_keys.openai} value={openai} onChange={setOpenai} />
            <KeyField id="gemini" label="Gemini API key" placeholder="AIzaSy…" masked={data.masked_keys.gemini} value={gemini} onChange={setGemini} />
          </div>

          <label className="switch switch-row">
            <input type="checkbox" checked={parallel} onChange={(e) => setParallel(e.target.checked)} />
            <span className="switch-track" />
            <span>
              <span className="choice-title">Run agents in parallel</span>
              <span className="choice-desc">Up to {data.max_concurrent_requests} model calls at once. Faster, but uses more of your rate limit.</span>
            </span>
          </label>

          <div className="compose-actions">
            <button className="btn btn-primary" disabled={!dirty || save.isPending}>{save.isPending ? <><Spinner /> Saving…</> : "Save settings"}</button>
          </div>
        </form>
      )}
    </div>
  );
}

function KeyField({ id, label, placeholder, masked, value, onChange }: {
  id: string; label: string; placeholder: string; masked: string; value: string; onChange: (v: string) => void;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="key-field">
      <label className="field-label" htmlFor={id}>{label}</label>
      <div className="input-affix">
        <input id={id} type={show ? "text" : "password"} autoComplete="off" spellCheck={false} value={value}
          onChange={(e) => onChange(e.target.value)} placeholder={masked ? `Saved: ${masked}. Enter a new key to replace it` : placeholder} />
        <button type="button" className="icon-btn" onClick={() => setShow(!show)} aria-label={show ? "Hide key" : "Show key"}>{show ? <EyeOff size={15} /> : <Eye size={15} />}</button>
      </div>
    </div>
  );
}
