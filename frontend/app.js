// FinSight sample frontend -- a single-page app (no tabs, one continuous workspace) that
// streams the multi-agent pipeline's activity as it happens, NotebookLM-style: sources/
// controls on the left, a live "thinking" feed in the center, results ("Studio") on the
// right. Plain HTML/CSS + vanilla JS -- no framework, no build step. Talks directly to the
// Flask API (CORS is already enabled there -- see app/__init__.py's CORS(app)).
const API_BASE = "http://localhost:5000/api";

const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATUSES = new Set(["COMPLETED", "FAILED", "NEEDS_ANALYST", "AWAITING_REVIEW"]);
const SESSIONS_KEY = "finsight.sessions";

const AGENT_META = {
  intake_classifier: { icon: "🗂️", label: "Intake", desc: "classifying the document" },
  extractor: { icon: "📐", label: "Extractor", desc: "parsing tables" },
  schema_mapper: { icon: "🔗", label: "Schema Mapper", desc: "mapping rows to the chart of accounts" },
  reconciler: { icon: "✅", label: "Reconciler", desc: "running statement checks" },
  ratio: { icon: "📊", label: "Ratio & Trend", desc: "computing financial ratios" },
  cash_wc: { icon: "💵", label: "Cash & Working Capital", desc: "" },
  forecast: { icon: "🔮", label: "Forecast", desc: "projecting future periods" },
  risk: { icon: "⚠️", label: "Risk & Anomaly", desc: "scanning for anomalies" },
  gst: { icon: "🧾", label: "GST Compliance", desc: "" },
  insight_reasoner: { icon: "💡", label: "Insight Reasoner", desc: "synthesizing findings" },
  chart_spec: { icon: "📈", label: "Chart Builder", desc: "rendering visualizations" },
  report_writer: { icon: "✍️", label: "Report Writer", desc: "drafting the report" },
  verifier: { icon: "🔍", label: "Verifier", desc: "checking claims against the data" },
  orchestrator: { icon: "🧭", label: "Orchestrator", desc: "relaying your note to the relevant agent(s)" },
};

// Statuses where the job is actively working -- the chat bar sends to the ORCHESTRATOR
// (mid-run steering) while in one of these, and to the Q&A agent otherwise (idle, or a
// terminal state like COMPLETED). See askOrSteer().
const ACTIVE_STATUSES = new Set([
  "CREATED", "INGESTING", "MAPPING", "RECONCILING", "DATA_VALIDATED", "ANALYZING",
  "SYNTHESIZING", "VERIFYING", "RENDERING",
]);

const STAGE_LABELS = { data: "Data stage", analysis: "Analysis stage", delivery: "Delivery stage" };

// ---------- state ----------

let currentJobId = null;
let currentJobStatus = null;
let renderedTaskIds = new Set();
let lastRenderedStage = null;
let pollGeneration = 0; // bumped whenever a new poll loop starts, so a stale one stops itself
let selectedFiles = [];
let chatHistory = [];

// ---------- small helpers ----------

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fmtNumber(value) {
  if (value === null || value === undefined) return "";
  const n = Number(value);
  return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function fmtTime(iso) {
  if (!iso) return "";
  return iso.includes("T") ? iso.split("T")[1].slice(0, 8) : iso;
}

async function apiGet(path, params) {
  const url = new URL(API_BASE + path);
  if (params) Object.entries(params).forEach(([k, v]) => v !== undefined && url.searchParams.set(k, v));
  const resp = await fetch(url);
  let body = null;
  try { body = await resp.json(); } catch (_) { /* non-JSON */ }
  return { ok: resp.ok, status: resp.status, body };
}

async function apiPostJson(path, payload) {
  const resp = await fetch(API_BASE + path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
  });
  let body = null;
  try { body = await resp.json(); } catch (_) { /* ignore */ }
  return { ok: resp.ok, status: resp.status, body };
}

async function apiDelete(path) {
  const resp = await fetch(API_BASE + path, { method: "DELETE" });
  let body = null;
  try { body = await resp.json(); } catch (_) { /* ignore */ }
  return { ok: resp.ok, status: resp.status, body };
}

function sleep(ms) { return new Promise((res) => setTimeout(res, ms)); }

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

const streamEl = document.getElementById("stream");
function scrollStreamToBottom() { streamEl.scrollTop = streamEl.scrollHeight; }

function clearStreamPlaceholder() {
  const placeholder = streamEl.querySelector(".stream-placeholder");
  if (placeholder) placeholder.remove();
}

// ---------- sessions (localStorage) ----------

function loadSessions() {
  try { return JSON.parse(localStorage.getItem(SESSIONS_KEY)) || []; } catch (_) { return []; }
}
function saveSession(jobId, goal) {
  const sessions = loadSessions().filter((s) => s.id !== jobId);
  sessions.unshift({ id: jobId, goal: goal || "", createdAt: new Date().toISOString() });
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, 20)));
  renderSessions();
}
function removeSessionLocal(jobId) {
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(loadSessions().filter((s) => s.id !== jobId)));
}
function renderSessions() {
  const list = document.getElementById("session-list");
  const sessions = loadSessions();
  if (!sessions.length) {
    list.innerHTML = `<li class="hint session-empty">No sessions yet.</li>`;
    return;
  }
  list.innerHTML = sessions.map((s) => `
    <li data-job-id="${escapeHtml(s.id)}" class="${s.id === currentJobId ? "active" : ""}">
      <div class="session-main">
        <div>${escapeHtml(s.goal || "Analysis")}</div>
        <div class="session-id">${escapeHtml(s.id)}</div>
      </div>
      <button class="session-delete" data-job-id="${escapeHtml(s.id)}" title="Delete this job">🗑</button>
    </li>`).join("");
  list.querySelectorAll("li[data-job-id] > .session-main").forEach((div) => {
    div.addEventListener("click", () => openJob(div.closest("li").dataset.jobId));
  });
  list.querySelectorAll(".session-delete").forEach((btn) => {
    btn.addEventListener("click", (e) => { e.stopPropagation(); deleteJob(btn.dataset.jobId); });
  });
}

/** Deletes a job server-side (documents, facts, metrics, findings, reports, review items,
 * task trace, and its on-disk files -- see DELETE /api/jobs/<id>) and drops it from this
 * browser's session list. If it's the currently-open job, resets the workspace to idle. */
async function deleteJob(jobId) {
  if (!confirm(`Delete this job (${jobId}) and everything generated from it? This can't be undone.`)) return;

  const { ok, status, body } = await apiDelete(`/jobs/${jobId}`);
  if (!ok) {
    alert(`Could not delete (${status}): ${(body && body.error) || "unknown error"}`);
    return;
  }
  removeSessionLocal(jobId);
  renderSessions();

  if (jobId === currentJobId) {
    pollGeneration++; // stop any in-flight poll loop for the deleted job
    currentJobId = null;
    currentJobStatus = null;
    renderedTaskIds = new Set();
    lastRenderedStage = null;
    streamEl.innerHTML = `<div class="stream-placeholder">
      <div class="stream-placeholder-icon">🧠</div>
      <p>This is where you'll watch the orchestrator hand work to each agent as it happens.</p>
    </div>`;
    document.getElementById("job-meta").textContent = "No job running yet — upload documents on the left to begin.";
    document.getElementById("progress-bar").style.width = "0%";
    setStatusPill("Idle");
    document.getElementById("status-pill").className = "status-pill status-pill-idle";
    hideReviewSection();
    resetStudio();
  }
}

// ---------- dropzone / file selection ----------

const dropzone = document.getElementById("dropzone");
const filesInput = document.getElementById("files-input");

dropzone.addEventListener("click", () => filesInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  addFiles(e.dataTransfer.files);
});
filesInput.addEventListener("change", () => { addFiles(filesInput.files); filesInput.value = ""; });

function addFiles(fileList) {
  for (const f of fileList) selectedFiles.push(f);
  renderFileList();
}
function renderFileList() {
  const listEl = document.getElementById("file-list");
  listEl.innerHTML = selectedFiles.map((f, i) => `
    <li><span>${escapeHtml(f.name)}</span><span class="file-remove" data-idx="${i}">✕</span></li>`).join("");
  listEl.querySelectorAll(".file-remove").forEach((btn) => {
    btn.addEventListener("click", () => { selectedFiles.splice(Number(btn.dataset.idx), 1); renderFileList(); });
  });
}

// ---------- stream rendering ----------

function addStageBanner(stage) {
  if (stage === lastRenderedStage) return;
  lastRenderedStage = stage;
  streamEl.appendChild(el(`<div class="stage-banner">${escapeHtml(STAGE_LABELS[stage] || stage)}</div>`));
}

function addTaskEntry(task) {
  const meta = AGENT_META[task.agent] || { icon: "🤖", label: task.agent, desc: "" };
  const confidence = task.confidence !== null && task.confidence !== undefined ? `confidence ${Number(task.confidence).toFixed(2)}` : "";
  const issuesHtml = (task.issues || []).length
    ? `<div class="entry-issues">${task.issues.map((i) => `<div>⚠ ${escapeHtml(i.message || i.code || "")}</div>`).join("")}</div>`
    : "";
  const entry = el(`
    <div class="entry">
      <div class="entry-icon">${meta.icon}</div>
      <div class="entry-body">
        <div class="entry-head">
          <span class="entry-agent">${escapeHtml(meta.label)}</span>
          <span class="badge badge-${escapeHtml((task.status || "").toLowerCase())}">${escapeHtml(task.status)}</span>
          <span class="entry-time">${escapeHtml(fmtTime(task.created_at))}</span>
        </div>
        <div class="entry-summary">${escapeHtml(task.summary || meta.desc)}</div>
        <div class="entry-meta">${escapeHtml(confidence)}</div>
        ${issuesHtml}
      </div>
    </div>`);
  streamEl.appendChild(entry);
}

let thinkingDotsEl = null;
function showThinkingDots() {
  hideThinkingDots();
  thinkingDotsEl = el(`<div class="thinking-dots"><span></span><span></span><span></span></div>`);
  streamEl.appendChild(thinkingDotsEl);
  scrollStreamToBottom();
}
function hideThinkingDots() {
  if (thinkingDotsEl) { thinkingDotsEl.remove(); thinkingDotsEl = null; }
}

async function renderNewTasks(jobId) {
  const { ok, body } = await apiGet(`/jobs/${jobId}/tasks`);
  if (!ok || !Array.isArray(body)) return;
  hideThinkingDots();
  let appended = false;
  for (const task of body) {
    if (renderedTaskIds.has(task.id)) continue;
    renderedTaskIds.add(task.id);
    const stage = agentToStage(task.agent);
    if (stage) addStageBanner(stage);
    addTaskEntry(task);
    appended = true;
  }
  if (appended) scrollStreamToBottom();
}

function agentToStage(agent) {
  if (["intake_classifier", "extractor", "schema_mapper", "reconciler"].includes(agent)) return "data";
  if (["ratio", "cash_wc", "forecast", "risk", "gst"].includes(agent)) return "analysis";
  if (["insight_reasoner", "chart_spec", "report_writer", "verifier"].includes(agent)) return "delivery";
  return null;
}

// ---------- status pill / progress ----------

function setStatusPill(status) {
  currentJobStatus = status;
  const pill = document.getElementById("status-pill");
  pill.textContent = status;
  let cls = "status-pill-running";
  if (status === "COMPLETED") cls = "status-pill-done";
  else if (status === "FAILED") cls = "status-pill-error";
  else if (["AWAITING_REVIEW", "NEEDS_ANALYST"].includes(status)) cls = "status-pill-warn";
  pill.className = "status-pill " + cls;
  updateChatHint();
}

function updateChatHint() {
  const hintEl = document.getElementById("chat-hint");
  if (ACTIVE_STATUSES.has(currentJobStatus)) {
    hintEl.textContent = "🧭 The job is running -- messages here steer the orchestrator (extra guidance/data), not a Q&A answer.";
    hintEl.classList.add("steering");
  } else {
    hintEl.textContent = "💬 Ask a question about this analysis.";
    hintEl.classList.remove("steering");
  }
}

// ---------- run pipeline ----------

async function runPipeline() {
  const goal = document.getElementById("goal-input").value || "Full financial analysis";
  const planTemplate = document.getElementById("template-input").value;
  const runBtn = document.getElementById("run-btn");

  if (!selectedFiles.length) {
    alert("Add at least one document first (drop it on the box above).");
    return;
  }

  const form = new FormData();
  for (const f of selectedFiles) form.append("files", f);
  form.append("goal", goal);
  form.append("plan_template", planTemplate);

  runBtn.disabled = true;
  document.getElementById("job-meta").textContent = "Uploading and creating job…";

  let resp;
  try {
    resp = await fetch(API_BASE + "/jobs", { method: "POST", body: form });
  } catch (exc) {
    document.getElementById("job-meta").textContent = `Could not reach the API: ${exc}`;
    runBtn.disabled = false;
    return;
  }
  const body = await resp.json().catch(() => ({}));
  if (resp.status !== 201 && resp.status !== 503) {
    document.getElementById("job-meta").textContent = `Failed to create job (${resp.status}): ${body.error || ""}`;
    runBtn.disabled = false;
    return;
  }

  const jobId = body.job_id;
  saveSession(jobId, goal);
  selectedFiles = [];
  renderFileList();

  if (resp.status === 503) {
    document.getElementById("job-meta").textContent = `Job ${jobId} created but the queue is unavailable: ${body.error || ""}`;
    runBtn.disabled = false;
    return;
  }

  startJobStream(jobId, goal);
  runBtn.disabled = false;
}

/** Resets the stream and begins watching a job -- used both right after creating a job and
 * when reopening a session/job id from the sidebar. */
function startJobStream(jobId, goal) {
  currentJobId = jobId;
  currentJobStatus = null;
  renderedTaskIds = new Set();
  lastRenderedStage = null;
  streamEl.innerHTML = "";
  document.getElementById("job-meta").textContent = `Job ${jobId}` + (goal ? ` — ${goal}` : "");
  document.getElementById("manual-job-id").value = jobId;
  renderSessions();
  hideReviewSection();
  resetStudio();
  pollJob(jobId);
}

async function openJob(jobId) {
  const sessions = loadSessions();
  const found = sessions.find((s) => s.id === jobId);
  startJobStream(jobId, found ? found.goal : "");
}

document.getElementById("run-btn").addEventListener("click", runPipeline);
document.getElementById("manual-open-btn").addEventListener("click", () => {
  const jobId = document.getElementById("manual-job-id").value.trim();
  if (jobId) openJob(jobId);
});

// ---------- polling loop ----------

async function pollJob(jobId) {
  const myGeneration = ++pollGeneration;
  showThinkingDots();
  for (let i = 0; i < 900; i++) { // ~30 min ceiling at 2s intervals
    if (pollGeneration !== myGeneration) return; // a newer job/session took over
    const { ok, body } = await apiGet(`/jobs/${jobId}`);
    if (ok && body) {
      setStatusPill(body.status);
      document.getElementById("progress-bar").style.width = `${body.progress_pct || 0}%`;
      document.getElementById("job-meta").textContent =
        `Job ${jobId} — [${body.stage || "?"}] ${body.progress_message || body.status}`;
      await renderNewTasks(jobId);

      if (body.status === "AWAITING_REVIEW") {
        hideThinkingDots();
        await showReviewGate(jobId);
        return;
      }
      if (TERMINAL_STATUSES.has(body.status)) {
        hideThinkingDots();
        if (body.status === "COMPLETED") await loadStudio(jobId);
        return;
      }
      showThinkingDots();
    }
    await sleep(POLL_INTERVAL_MS);
  }
  hideThinkingDots();
  document.getElementById("job-meta").textContent = "Timed out waiting for the job to finish (30 min).";
}

// ---------- review gate (inline in the stream + mirrored in Studio) ----------

async function showReviewGate(jobId) {
  const { ok, body } = await apiGet("/review/items", { job_id: jobId });
  if (!ok) return;
  const items = body || [];
  const recon = items.filter((i) => i.kind === "reconciliation");
  const mapping = items.filter((i) => i.kind === "mapping");

  if (recon.length) {
    const card = el(`
      <div class="review-entry">
        <h4>⏸ Needs your review — ${recon.length} reconciliation item(s)</h4>
        <div class="hint">A deterministic check didn't tie out. See the Studio panel on the right to
        read each one and accept them so the pipeline can continue.</div>
      </div>`);
    streamEl.appendChild(card);
    scrollStreamToBottom();
  }

  renderReviewSection(recon, mapping);
}

function hideReviewSection() {
  document.getElementById("review-section").classList.add("hidden");
}

function renderReviewSection(recon, mapping) {
  const section = document.getElementById("review-section");
  if (!recon.length) { section.classList.add("hidden"); return; }
  section.classList.remove("hidden");

  document.getElementById("recon-list").innerHTML = recon.map((item) => {
    const p = item.payload || {};
    return `<div class="recon-item" data-id="${escapeHtml(item.id)}">
      <div class="recon-code">${escapeHtml(p.check_code)}</div>
      <div class="recon-nums">expected ${fmtNumber(p.expected)} vs actual ${fmtNumber(p.actual)} (diff ${fmtNumber(p.diff)})</div>
      <div class="recon-explain">${escapeHtml(p.explanation)}</div>
    </div>`;
  }).join("");

  const mappingBody = document.querySelector("#mapping-table tbody");
  mappingBody.innerHTML = mapping.length ? mapping.map((item) => {
    const p = item.payload || {};
    return `<tr><td class="mono">${escapeHtml(item.id)}</td><td>${escapeHtml(p.label)}</td>` +
      `<td class="mono">${escapeHtml(p.suggested_account_id)}</td><td>${fmtNumber(p.confidence)}</td></tr>`;
  }).join("") : `<tr><td colspan="4" class="hint">None.</td></tr>`;
}

async function acceptReconciliationAndResume() {
  if (!currentJobId) return;
  const btn = document.getElementById("accept-recon-btn");
  const { ok, body } = await apiGet("/review/items", { job_id: currentJobId });
  if (!ok) return;
  const reconItems = (body || []).filter((i) => i.kind === "reconciliation");
  if (!reconItems.length) return;

  btn.disabled = true;
  for (const item of reconItems) {
    await apiPostJson(`/review/items/${item.id}/resolve`, { note: "accepted via sample frontend" });
  }
  hideReviewSection();
  streamEl.appendChild(el(`<div class="hint" style="padding:0.5rem 0;">✓ Accepted ${reconItems.length} reconciliation item(s) — resuming…</div>`));
  scrollStreamToBottom();
  btn.disabled = false;
  pollJob(currentJobId);
}

async function correctMapping() {
  const itemId = document.getElementById("correct-item-id").value.trim();
  const accountId = document.getElementById("correct-account-id").value.trim();
  const msgEl = document.getElementById("correct-result-msg");
  if (!itemId || !accountId) { msgEl.textContent = "Enter both fields above."; return; }
  const { ok, status, body } = await apiPostJson(`/review/items/${itemId}/resolve`, { account_id: accountId });
  msgEl.textContent = ok ? `Corrected to ${accountId}.` : `Error (${status}): ${(body && body.error) || "failed"}`;
}

document.getElementById("accept-recon-btn").addEventListener("click", acceptReconciliationAndResume);
document.getElementById("correct-mapping-btn").addEventListener("click", correctMapping);

// ---------- studio (results) ----------

function resetStudio() {
  document.getElementById("report-empty").classList.remove("hidden");
  document.getElementById("report-actions").classList.add("hidden");
  document.getElementById("report-frame").classList.add("hidden");
  document.getElementById("report-frame").src = "";
  document.getElementById("charts-empty").classList.remove("hidden");
  document.getElementById("charts-gallery").innerHTML = "";
  document.querySelector("#metrics-table tbody").innerHTML = "";
  document.querySelector("#findings-table tbody").innerHTML = "";
}

async function loadStudio(jobId) {
  const [metricsRes, findingsRes, chartsRes] = await Promise.all([
    apiGet(`/jobs/${jobId}/metrics`), apiGet(`/jobs/${jobId}/findings`), apiGet(`/jobs/${jobId}/charts`),
  ]);

  const metricsBody = document.querySelector("#metrics-table tbody");
  metricsBody.innerHTML = (metricsRes.ok && metricsRes.body || []).map((m) =>
    `<tr><td class="mono">${escapeHtml(m.metric_code)}</td><td>${escapeHtml(m.period_end)}</td>` +
    `<td>${fmtNumber(m.value)}</td><td>${escapeHtml(m.unit)}</td></tr>`).join("") ||
    `<tr><td colspan="4" class="hint">No metrics.</td></tr>`;

  const findingsBody = document.querySelector("#findings-table tbody");
  findingsBody.innerHTML = (findingsRes.ok && findingsRes.body || []).map((f) =>
    `<tr><td>${escapeHtml(f.module)}</td><td>${escapeHtml(f.severity)}</td><td>${escapeHtml(f.title)}</td></tr>`).join("") ||
    `<tr><td colspan="3" class="hint">No findings.</td></tr>`;

  const charts = (chartsRes.ok && chartsRes.body) || [];
  const galleryEl = document.getElementById("charts-gallery");
  if (charts.length) {
    document.getElementById("charts-empty").classList.add("hidden");
    galleryEl.innerHTML = charts.map((c) => `
      <div class="chart-card">
        <img src="${c.png_base64}" alt="${escapeHtml(c.title)}">
        <div class="chart-title">${escapeHtml(c.title)}</div>
        ${c.caption ? `<div class="chart-caption">${escapeHtml(c.caption)}</div>` : ""}
      </div>`).join("");
  } else {
    document.getElementById("charts-empty").classList.remove("hidden");
    galleryEl.innerHTML = "";
  }

  const reportResp = await fetch(`${API_BASE}/jobs/${jobId}/report?format=html`);
  if (reportResp.ok) {
    document.getElementById("report-empty").classList.add("hidden");
    document.getElementById("report-actions").classList.remove("hidden");
    const frame = document.getElementById("report-frame");
    frame.classList.remove("hidden");
    frame.src = `${API_BASE}/jobs/${jobId}/report?format=html`;
    document.getElementById("download-docx").href = `${API_BASE}/jobs/${jobId}/report?format=docx`;
    document.getElementById("download-pdf").href = `${API_BASE}/jobs/${jobId}/report?format=pdf`;
  }
}

document.getElementById("studio-refresh-btn").addEventListener("click", () => {
  if (currentJobId) loadStudio(currentJobId);
});

// ---------- ask a question (chat, inline in the stream) ----------

/** While the job is actively running, the chat bar steers the pipeline (POST
 * /jobs/<id>/instructions) instead of asking the post-hoc QA agent -- the orchestrator
 * picks it up at the next stage boundary and relays it to whichever agents it's relevant
 * to (see apply_pending_instructions), which shows up as a new "🧭 Orchestrator" entry in
 * this same stream once that happens. Once the job is idle/terminal, the SAME input goes
 * to the regular QA agent instead, unchanged from before. */
const AUTO_DECIDE_KEY = "finsight.autoDecide";
const autoDecideToggle = document.getElementById("auto-decide-toggle");
autoDecideToggle.checked = localStorage.getItem(AUTO_DECIDE_KEY) === "1";
autoDecideToggle.addEventListener("change", () => {
  localStorage.setItem(AUTO_DECIDE_KEY, autoDecideToggle.checked ? "1" : "0");
});

async function askOrSteer() {
  const input = document.getElementById("ask-input");
  const question = input.value.trim();
  if (!question) return;
  if (!currentJobId) { alert("Run or open a job first."); return; }

  const isSteering = ACTIVE_STATUSES.has(currentJobStatus);

  clearStreamPlaceholder();
  const entry = el(`
    <div class="chat-entry">
      <div class="chat-bubble chat-bubble-user">${escapeHtml(question)}</div>
    </div>`);
  streamEl.appendChild(entry);
  input.value = "";
  scrollStreamToBottom();

  if (isSteering) {
    const { ok, status, body } = await apiPostJson(`/jobs/${currentJobId}/instructions`, { content: question });
    const noteText = ok
      ? "Sent to the orchestrator -- it'll be relayed to the relevant agent(s) at the next stage boundary. " +
        "Watch the stream above for a 🧭 Orchestrator entry confirming it was picked up."
      : `Error (${status}): ${(body && body.error) || "could not send"}`;
    entry.appendChild(el(`<div class="chat-bubble chat-bubble-answer">${escapeHtml(noteText)}</div>`));
    entry.appendChild(el(`<div class="chat-meta">${isSteering ? "steering note" : ""}</div>`));
    scrollStreamToBottom();
    return;
  }

  // Idle/terminal: try the orchestrator-driven assistant first (it re-runs a specific
  // analysis agent on demand, e.g. "redo the risk score excluding the one-off item").
  // If it can't match the request to any agent, fall back to the regular QA lookup --
  // from the user's point of view this is one chat box that just handles both.
  showThinkingDots();
  scrollStreamToBottom();
  await runAssistant(currentJobId, entry, { message: question });
}

/** Runs the assistant endpoint and renders whatever it comes back with: a clarification
 * (Claude-Code-style option buttons), a resolved agent answer, or -- if it couldn't match
 * an agent at all -- transparently falls back to the plain QA lookup. `payload` is either
 * {message} for a fresh request or {chosen_agent, action_note} for a clarification
 * follow-up (see index.html's clarify-option buttons). */
async function runAssistant(jobId, entry, payload) {
  const auto = autoDecideToggle.checked;
  const { ok, status, body } = await apiPostJson(`/jobs/${jobId}/assistant`, { ...payload, auto });
  hideThinkingDots();

  if (!ok) {
    entry.appendChild(el(`<div class="chat-bubble chat-bubble-answer">Error (${status}): ${escapeHtml((body && body.error) || "request failed")}</div>`));
    scrollStreamToBottom();
    return;
  }

  if (body.type === "clarification") {
    renderClarificationCard(jobId, entry, body.question, body.options);
    return;
  }

  // agent_used === null means the assistant didn't think this needed an agent re-run --
  // fall back to the normal QA lookup rather than showing a dead-end message.
  if (!body.agent_used && payload.message) {
    const qa = await apiPostJson("/qa", {
      job_id: jobId,
      question: payload.message,
      history: chatHistory.slice(-4),
    });
    const answerText = qa.ok
      ? qa.body.answer + (qa.body.citations && qa.body.citations.length ? `\n\nCitations: ${qa.body.citations.join(", ")}` : "")
      : `Error (${qa.status}): ${(qa.body && qa.body.error) || "request failed"}`;
    entry.appendChild(el(`<div class="chat-bubble chat-bubble-answer">${escapeHtml(answerText)}</div>`));
    entry.appendChild(el(`<div class="chat-meta">${qa.ok ? "route: " + escapeHtml(qa.body.route) : ""}</div>`));
    scrollStreamToBottom();
    if (qa.ok) {
      chatHistory.push({ role: "user", content: payload.message });
      chatHistory.push({ role: "assistant", content: qa.body.answer });
    }
    return;
  }

  entry.appendChild(el(`<div class="chat-bubble chat-bubble-answer">${escapeHtml(body.answer)}</div>`));
  entry.appendChild(el(`<div class="chat-meta">${body.agent_used ? "agent: " + escapeHtml(body.agent_used) : ""}</div>`));
  scrollStreamToBottom();
  if (payload.message) {
    chatHistory.push({ role: "user", content: payload.message });
    chatHistory.push({ role: "assistant", content: body.answer });
  }
  // The on-demand agent run recorded its own TaskRun (see jobs.py's ask_assistant) --
  // pick it up into the SAME unified stream as a proper entry, same as a pipeline-triggered
  // run, instead of just leaving it as plain chat text.
  if (body.agent_used) {
    await renderNewTasks(jobId);
    if (body.agent_used === "report_writer") {
      await loadStudio(jobId);
    }
  }
}

function renderClarificationCard(jobId, entry, question, options) {
  const card = el(`
    <div class="clarify-card">
      <div class="clarify-question">${escapeHtml(question)}</div>
      ${options.map((o, i) => `
        <button class="clarify-option" data-idx="${i}">
          <div class="clarify-option-label">${escapeHtml(o.label)}</div>
          <div class="clarify-option-desc">${escapeHtml(o.description)}</div>
        </button>`).join("")}
    </div>`);
  entry.appendChild(card);
  scrollStreamToBottom();

  card.querySelectorAll(".clarify-option").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const chosen = options[Number(btn.dataset.idx)];
      card.querySelectorAll(".clarify-option").forEach((b) => { b.disabled = true; });
      const pickedEntry = el(`<div class="chat-entry"><div class="chat-bubble chat-bubble-user">${escapeHtml(chosen.label)}</div></div>`);
      streamEl.appendChild(pickedEntry);
      showThinkingDots();
      scrollStreamToBottom();
      await runAssistant(jobId, pickedEntry, { chosen_agent: chosen.agent, action_note: chosen.description });
    });
  });
}

document.getElementById("ask-btn").addEventListener("click", askOrSteer);
document.getElementById("ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") askOrSteer(); });

// ---------- LLM & API keys ----------

function llmApiBase() {
  return API_BASE.endsWith("/api") ? API_BASE.slice(0, -4) + "/api/llm" : API_BASE + "/llm";
}

async function refreshLlmStatus() {
  const statusEl = document.getElementById("llm-status");
  try {
    const resp = await fetch(llmApiBase() + "/status");
    if (!resp.ok) { statusEl.textContent = `LLM status unavailable (${resp.status}).`; return; }
    const data = await resp.json();
    const keys = [];
    if (data.keys_configured.openai) keys.push(`OpenAI: ${data.masked_keys.openai}`);
    if (data.keys_configured.gemini) keys.push(`Gemini: ${data.masked_keys.gemini}`);
    if (data.keys_configured.custom) keys.push("Custom endpoint key set");
    statusEl.textContent =
      `Active: ${data.active_model} (${data.resolved_backend})\n` +
      `Backend: ${data.configured_backend}\n` +
      `Parallel: ${data.parallel_calls ? "on" : "off"} (max ${data.max_concurrent_requests})\n` +
      `Keys: ${keys.length ? keys.join(" | ") : "none (using fake mock)"}`;
    document.getElementById("backend-select").value = data.configured_backend;
    document.getElementById("parallel-checkbox").checked = !!data.parallel_calls;
  } catch (exc) {
    statusEl.textContent = `Could not reach FinSight LLM API: ${exc}`;
  }
}

async function saveLlmSettings() {
  const backend = document.getElementById("backend-select").value;
  const openaiKey = document.getElementById("openai-key-input").value.trim();
  const geminiKey = document.getElementById("gemini-key-input").value.trim();
  const parallel = document.getElementById("parallel-checkbox").checked;
  const msgEl = document.getElementById("llm-save-msg");

  const payload = { backend, parallel_calls: parallel };
  if (openaiKey) payload.openai_api_key = openaiKey;
  if (geminiKey) payload.gemini_api_key = geminiKey;

  try {
    const resp = await fetch(llmApiBase() + "/config", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    if (resp.ok) {
      msgEl.textContent = "Saved.";
      document.getElementById("openai-key-input").value = "";
      document.getElementById("gemini-key-input").value = "";
      await refreshLlmStatus();
    } else {
      const body = await resp.json().catch(() => ({}));
      msgEl.textContent = `Error (${resp.status}): ${body.error || "could not save"}`;
    }
  } catch (exc) {
    msgEl.textContent = `Failed: ${exc}`;
  }
}

document.getElementById("llm-refresh-btn").addEventListener("click", refreshLlmStatus);
document.getElementById("llm-save-btn").addEventListener("click", saveLlmSettings);

// ---------- init ----------

renderSessions();
refreshLlmStatus();
updateChatHint();
