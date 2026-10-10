import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, Compass, X } from "lucide-react";
import { api } from "../lib/api";
import { refreshResults } from "../lib/hooks";
import { agentDef, isActive } from "../lib/pipeline";
import { METRICS, metricLabel } from "../lib/format";
import type { Chart, Instruction, Job } from "../lib/types";
import { Spinner } from "./ui";

interface Option { label: string; description: string; agent: string }
interface Msg {
  id: string;
  role: "user" | "assistant";
  text: string;
  kind?: "steer" | "error";
  instructionId?: string;
  meta?: string;
  citations?: string[];
  options?: Option[];
  answered?: boolean;
  chart?: Chart;
}

/** Citations are metric codes or internal ids; show the readable name where there is one. */
function sourceLabel(c: string) {
  if (METRICS[c]) return metricLabel(c);
  if (c === "report_findings") return "analysis findings";
  if (c.startsWith("query_result")) return "computed metrics";
  return c.replace(/_/g, " ");
}

const storeKey = (jobId: string) => `finsight.chat.${jobId}`;
const AUTO_KEY = "finsight.autoDecide";
const uid = () => Math.random().toString(36).slice(2, 10);

const ASK_PROMPTS = [
  "Why did the EBITDA margin change?",
  "Is working capital getting tighter?",
  "What are the biggest risks for a lender?",
  "Re-run the risk score excluding one-off items",
];
const DONE_NOTE: Record<string, string> = {
  report_writer: "Report regenerated and re-verified. Open the Report tab to read it.",
  chart_spec: "Charts redrawn. They're in the Charts tab.",
  insight_reasoner: "Insights refreshed.",
  forecast: "Forecast recomputed. Updated figures are in the Overview.",
  risk: "Risk score recomputed. Updated findings are in the Overview.",
};

const BANK_PROMPTS = [
  "How many months of cash cover are there?",
  "How concentrated are the receipts?",
  "Is the cash position getting better or worse?",
  "What are the biggest risks for a lender?",
];

const STEER_PROMPTS = [
  "Treat the FY24 other income as one-off",
  "Focus the report on debt servicing capacity",
];

export function ChatPanel({ job, instructions, onClose }: { job: Job; instructions: Instruction[]; onClose?: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>(() => {
    try { return JSON.parse(localStorage.getItem(storeKey(job.id)) ?? "[]"); } catch { return []; }
  });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("Working it out…");
  const [auto, setAuto] = useState(() => localStorage.getItem(AUTO_KEY) === "1");
  const [chatZoom, setChatZoom] = useState<Chart | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const qc = useQueryClient();
  const steering = isActive(job.status);
  const canAsk = !!job.dataset_version_id;

  useEffect(() => { localStorage.setItem(storeKey(job.id), JSON.stringify(msgs.slice(-60))); }, [msgs, job.id]);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [msgs, busy]);
  useEffect(() => { localStorage.setItem(AUTO_KEY, auto ? "1" : "0"); }, [auto]);

  const push = (m: Omit<Msg, "id">) => setMsgs((cur) => [...cur, { ...m, id: uid() }]);

  const history = () => msgs.filter((m) => !m.kind && !m.options).slice(-4).map((m) => ({ role: m.role, content: m.text }));

  async function runAssistant(payload: { message?: string; chosen_agent?: string; action_note?: string; force?: boolean }) {
    const res = await api.assistant(job.id, { ...payload, auto });
    if (res.type === "clarification") {
      push({ role: "assistant", text: res.question, options: res.options });
      return;
    }
    if (!res.agent_used && payload.message && !payload.force) {
      const qa = await api.qa(job.id, payload.message, history());
      // The Q&A router judged this to be a request to recompute something, not a question:
      // run it rather than replying with instructions on how to ask for it.
      if (qa.route === "action_request") {
        setBusyLabel("Running it now…");
        await runAssistant({ message: payload.message, force: true });
        return;
      }
      push({ role: "assistant", text: qa.answer, citations: qa.citations, chart: qa.chart ?? undefined });
      if (qa.chart) {
        refreshResults(qc, job.id);
      }
      return;
    }
    if (!res.agent_used) {
      push({ role: "assistant", text: "I couldn't tell which part of the analysis to redo. Try naming it, for example “regenerate the report” or “re-run the forecast”." });
      return;
    }
    push({ role: "assistant", text: res.answer, meta: DONE_NOTE[res.agent_used] ?? `Re-ran ${agentDef(res.agent_used).label}.` });
    refreshResults(qc, job.id);
  }

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    push({ role: "user", text: q, kind: steering ? "steer" : undefined });
    setBusyLabel(steering ? "Sending…" : "Working it out…");
    setBusy(true);
    try {
      if (steering) {
        const ins = await api.addInstruction(job.id, q);
        setMsgs((cur) => cur.map((m, i) => (i === cur.length - 1 ? { ...m, instructionId: ins.id } : m)));
        qc.invalidateQueries({ queryKey: ["instructions", job.id] });
      } else {
        await runAssistant({ message: q });
      }
    } catch (e) {
      push({ role: "assistant", text: (e as Error).message, kind: "error" });
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  async function choose(msgId: string, opt: Option) {
    setMsgs((cur) => cur.map((m) => (m.id === msgId ? { ...m, answered: true } : m)));
    push({ role: "user", text: opt.label });
    setBusyLabel(`Running ${agentDef(opt.agent).label.toLowerCase()}…`);
    setBusy(true);
    try { await runAssistant({ chosen_agent: opt.agent, action_note: opt.description }); }
    catch (e) { push({ role: "assistant", text: (e as Error).message, kind: "error" }); }
    finally { setBusy(false); }
  }

  const insById = new Map(instructions.map((i) => [i.id, i]));
  const prompts = steering ? STEER_PROMPTS : job.plan_template === "bank_statement_review" ? BANK_PROMPTS : ASK_PROMPTS;
  const disabled = !steering && !canAsk;

  return (
    <aside className="chat" aria-label="Ask FinSight">
      <header className="chat-head">
        <div>
          <h2>{steering ? "Guide this run" : "Ask about this analysis"}</h2>
          <p>{steering
            ? "Notes are picked up at the next stage and passed to the agents they concern."
            : "Answers are drawn from the verified figures. Ask for a re-run to recompute with new assumptions."}</p>
        </div>
        {onClose && <button className="icon-btn" aria-label="Close panel" onClick={onClose}><X size={16} /></button>}
      </header>

      <div className="chat-scroll" ref={scrollRef} aria-live="polite">
        {!msgs.length && (
          <div className="chat-empty">
            {disabled ? <p className="muted small">Questions open once the data has been read and reconciled.</p> : (
              <>
                <p className="muted small">Try one of these</p>
                {prompts.map((p) => <button key={p} className="prompt" onClick={() => send(p)}>{p}</button>)}
              </>
            )}
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className={`msg msg-${m.role} ${m.kind === "error" ? "msg-error" : ""}`}>
            {m.role === "user" ? (
              <div className="msg-user-text">
                {m.kind === "steer" && <span className="steer-tag"><Compass size={12} /> Guidance</span>}
                {m.text}
                {m.instructionId && <InstructionStatus ins={insById.get(m.instructionId)} />}
              </div>
            ) : (
              <div className="msg-answer">
                <div className="prose"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown></div>
                {m.chart && (
                  <figure className="chat-chart" style={{ marginTop: 10, marginBottom: 10, borderRadius: 8, overflow: "hidden", border: "1px solid var(--border, #cbd5e1)", background: "var(--card-bg, #ffffff)" }}>
                    <button
                      type="button"
                      style={{ border: "none", background: "none", padding: 0, width: "100%", cursor: "pointer", display: "block" }}
                      onClick={() => setChatZoom(m.chart!)}
                      aria-label={`Enlarge ${m.chart.title}`}
                    >
                      <img src={m.chart.png_base64} alt={m.chart.title} style={{ width: "100%", display: "block" }} />
                    </button>
                    <figcaption style={{ padding: "8px 12px", background: "var(--bg-subtle, #f8fafc)", borderTop: "1px solid var(--border, #e2e8f0)", fontSize: 12 }}>
                      <strong style={{ display: "block", color: "var(--text, #0f172a)", marginBottom: 2 }}>{m.chart.title}</strong>
                      {m.chart.takeaway && <span style={{ color: "var(--muted, #64748b)" }}>{m.chart.takeaway}</span>}
                    </figcaption>
                  </figure>
                )}
                {m.options && (
                  <div className="options">
                    {m.options.map((o) => (
                      <button key={o.agent + o.label} className="option" disabled={m.answered || busy} onClick={() => choose(m.id, o)}>
                        <span className="option-label">{o.label}</span>
                        <span className="option-desc">{o.description}</span>
                      </button>
                    ))}
                  </div>
                )}
                {!!m.citations?.length && <div className="msg-meta">Sources: {m.citations.map(sourceLabel).join(", ")}</div>}
                {m.meta && <div className="msg-meta">{m.meta}</div>}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg msg-assistant"><div className="typing"><Spinner size={12} /> {busyLabel}</div></div>}
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <textarea
          ref={inputRef}
          rows={2}
          value={input}
          disabled={disabled}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
          placeholder={disabled ? "Available once the data is ready" : steering ? "Add guidance for the agents…" : "Ask a question…"}
          aria-label="Message"
        />
        <div className="composer-row">
          {!steering ? (
            <label className="switch" title="When the request could mean more than one agent, pick the best match instead of asking you.">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              <span className="switch-track" /> Choose the agent for me
            </label>
          ) : <span />}
          <button className="send" type="submit" disabled={!input.trim() || busy || disabled} aria-label="Send"><ArrowUp size={16} /></button>
        </div>
      </form>

      {chatZoom && (
        <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && setChatZoom(null)}>
          <figure className="lightbox" role="dialog" aria-modal="true" aria-label={chatZoom.title}>
            <button className="icon-btn lightbox-close" onClick={() => setChatZoom(null)} aria-label="Close"><X size={18} /></button>
            <img src={chatZoom.png_base64} alt={chatZoom.title} />
            <figcaption><strong>{chatZoom.title}</strong>{chatZoom.caption && <span>{chatZoom.caption}</span>}</figcaption>
          </figure>
        </div>
      )}
    </aside>
  );
}

function InstructionStatus({ ins }: { ins: Instruction | undefined }) {
  if (!ins) return null;
  if (ins.status === "pending") return <div className="ins-status">Waiting for the next stage</div>;
  if (ins.status === "applied") {
    const who = (ins.target_agents ?? []).map((a) => agentDef(a).label).join(", ");
    return <div className="ins-status ins-applied">Applied{who ? ` to ${who}` : ""}{ins.orchestrator_note ? `. ${ins.orchestrator_note}` : ""}</div>;
  }
  return <div className="ins-status">Not applied{ins.orchestrator_note ? `: ${ins.orchestrator_note}` : ""}</div>;
}
