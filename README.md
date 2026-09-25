# FinSight — Multi-Agent Financial Analysis Backend (Flask)

A Flask backend that ingests multiple financial documents (P&L, balance sheet, cash flow,
bank statements, GST returns) in Excel/CSV/PDF form — including multi-sheet workbooks and
files with metadata above the real table — runs them through a multi-agent pipeline
(orchestrator → data/analysis/delivery supervisors → worker agents, each with a fixed tool
allowlist), and produces a validated financial ledger, computed metrics, findings, a
number-bound report (HTML/DOCX/PDF), and an interactive Q&A endpoint. Two separate UIs
talk to the same Flask API over HTTP: a Gradio UI (`gradio_app.py`) with upload-and-watch
access to the whole pipeline, including a live, row-per-agent trace of what each worker in
the multi-agent system is doing; and a plain HTML/CSS/JS sample frontend (`frontend/`,
served by a thin FastAPI process, `frontend_server.py`) covering the same features for
anyone who'd rather not run Gradio.

This is a scoped-down implementation of `financial_agent_system_design.md` /
`financial_agent_mermaid_diagrams.md` — see the "Scoping decisions" section below for
exactly what was simplified and why (Celery+Redis instead of Temporal, SQLite instead of
Postgres/pgvector, matplotlib instead of vl-convert, etc.). The agent hierarchy, tool
allowlists, stage gates, reconciliation checks, and number-binding/verification pipeline
are all real, not stubs.

**No login.** This runs as a direct/local application, not a multi-tenant SaaS — every API
call resolves to one fixed default tenant/entity (`app/utils/default_tenant.py`, created by
`flask init-db`). The `tenant_id` columns are still there under the hood (ripping them out
would be a much bigger, riskier change for what's really a UX simplification), they just
never vary.

---

### Key Capabilities & Architectural Innovations

- 🧠 **Virtual CFO Financial Intelligence Engine** (`app/domain/financial_intelligence.py`):
  Comprehensive diagnostic engine modeling **40 core financial metrics** across a **6-level reverse-flow drill-down**:
  1. *Formula*: Governing mathematical equation.
  2. *Governing Components*: Structural balance sheet / P&L components.
  3. *Operational Drivers*: Real-world business operations driving financial results.
  4. *Root Causes*: Exhaustive underlying causes (mix shifts, commodity cycles, bottlenecks, leakage).
  5. *What to Investigate*: Concrete operational data, sub-meters, logs, and aging ledgers.
  6. *What to Ask Management*: High-impact CFO questions and strategic action points.
  Answers automated reverse-flow diagnostic queries: *What changed? Why did it change? What caused it? What to investigate? What to ask management?*

- 📊 **Deterministic Report Redesign & Executive Visual Layer** (`app/domain/taxonomy.py`, `app/tools/report_render.py`):
  - **Taxonomy-Anchored Skeletons**: Reports follow a predictable, ordered structure (`build_report_skeleton()`) anchored in verified data rather than LLM improvisation.
  - **Interleaved Chart Embeddings**: High-resolution trend visualizations are seamlessly embedded directly into their corresponding narrative domain sections.
  - **Executive Presentation Layer**: Premium cover banner, composite financial health score indicator, and executive KPI performance overview grid — fully cross-compatible with HTML, DOCX, and PDF (xhtml2pdf compliant).

- 💬 **Interactive Chat Assistant & Reverse-Flow Q&A** (`app/agents/delivery/qa.py`, `app/api/qa.py`):
  - **Diagnostic Routing**: Automatically identifies diagnostic queries (*"Why did EBITDA margin decline?"*, *"What caused current ratio to drop?"*) and generates structured 5-point Virtual CFO reverse-flow diagnostic traces.
  - **Multi-Turn Conversation Memory**: Tracks conversation history across turns in both Gradio and the web frontend.
  - **On-Demand Delivery Agent Re-Runs**: Users can steer or re-run delivery agents (`report_writer`, `insight_reasoner`, `chart_spec`) from chat, auto-regenerating verified reports and visual artifacts.

---

## Quickstart — Docker (recommended for local testing)

This is the easiest way to run the whole stack (API + Celery worker + Redis + Gradio UI)
on Windows without touching native Celery/Redis quirks. Requires Docker Desktop running.

```powershell
copy .env.docker.example .env.docker
docker compose up --build
```

`.env.docker` isn't committed (it can hold a real LLM API key) -- `.env.docker.example` is
the tracked template, same pattern as `.env`/`.env.example` for the native path. It
defaults to `LLM_BACKEND=fake`, so the stack runs end to end before you have real LLM
credentials.

That builds one image (shared by the `api`, `worker`, `gradio`, and `frontend` services),
starts Redis, runs a one-shot `init` container (`flask init-db` — idempotent, safe to
re-run), then starts the API on `http://localhost:5000`, a Celery worker connected to
Redis, a **Gradio UI on `http://localhost:7860`**, and the **plain HTML/CSS/JS sample
frontend on `http://localhost:8080`**. Data persists in the `instance_data` named volume
across restarts; `docker compose down -v` wipes it for a clean slate.

Open `http://localhost:7860` and, on the "Run analysis" tab, upload the sample files in
`seed/data/` (or your own), hit "Run pipeline", and watch the job's stage/status/progress
update live alongside a **row-per-agent task trace** (intake, extract, map, reconcile,
each analysis module, insight, chart spec, report writer, verifier — exactly what ran,
when, and with what confidence). The "Results" tab shows metrics, findings, and the
rendered report (inline HTML, downloadable DOCX/PDF); "Ask a question" hits the QA agent.

**Plain HTML/CSS/JS frontend**: `http://localhost:8080` covers the same five workflows as
the Gradio tabs — run analysis, review & approve, results, ask a question, LLM & API keys —
as a single static page (`frontend/index.html` + `style.css` + `app.js`, no build step, no
JS framework), served by `frontend_server.py` (a FastAPI app that does nothing but serve
those static files — `uvicorn frontend_server:app`). Its JS calls the Flask API directly
from the browser at `http://localhost:5000/api` (CORS is already enabled on the Flask app
for this — see `app/__init__.py`'s `CORS(app)`); if you're serving the API from somewhere
other than `localhost:5000`, change the `API_BASE` constant at the top of `frontend/app.js`.
It's a genuinely separate, independent client of the same API — not a proxy, not a fork of
the Gradio app — so either UI, both, or neither can be running at once.

`seed/data/multi_sheet_statements.xlsx` is a second demo file worth trying: one workbook,
two sheets (Balance Sheet, P&L), each with a metadata preamble (company name, report
title) above the real table -- it exercises the header-row detection and per-sheet
extraction described under "Extraction robustness" below, not just the single-table case.

Prefer the command line? Same job, from a second host terminal:

```powershell
python seed/upload_demo_job.py
```

This uploads the sample CSVs in `seed/data/` and polls the job — end to end through the
*real* Celery/Redis dispatch path (unlike `pytest`'s e2e test, which calls the stage
supervisors directly and doesn't need a broker). Watch it happen live with `docker compose
logs -f worker`.

To use a real LLM instead of the fake one, edit `.env.docker` (see "Switching LLM
providers" below) — paste an OpenAI or Gemini key in and it's picked up automatically, or
point `LLM_BASE_URL` at your own deployment (`http://host.docker.internal:<port>/v1` if
it's on the Windows host rather than in Docker). Then `docker compose up --build` again.

Useful commands: `docker compose logs -f api` / `worker`, `docker compose exec api flask
shell`, `docker compose down` (stop, keep data), `docker compose down -v` (stop, wipe data).

## Quickstart — native (Windows, no Docker)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

`.env` defaults to `LLM_BACKEND=fake` (a deterministic stand-in LLM, see
`app/llm_gateway/fake_client.py`) and SQLite, so you can run the whole pipeline before you
have real LLM credentials.

```powershell
flask init-db
```

(`flask seed-demo` still exists as a deprecated no-op alias for older muscle memory --
`init-db` already sets up the default tenant.)

You need Redis for Celery (the job queue) reachable at `localhost:6379` — the easiest way
is still `docker run -p 6379:6379 redis` (or just use the full Docker Compose setup above
instead of this native path), or WSL/Memurai if you'd rather not touch Docker at all. Then,
in separate terminals:

```powershell
celery -A app.workers.celery_app worker --pool=solo -l info
python run.py
```

`--pool=solo` is required on Windows — Celery's default prefork pool isn't supported there.
Concurrency within a pipeline stage still happens via an in-process thread pool (see
`app/agents/data/supervisor.py`), so this doesn't reduce parallelism. (Inside Docker, the
worker runs Celery's normal prefork pool instead — see docker-compose.yml.)

### Try it

```powershell
python seed/upload_demo_job.py
```

This uploads the sample P&L/balance sheet/cash flow/bank statement CSVs in `seed/data/`,
and polls the job until it completes. Then:

```
GET    /api/jobs/<job_id>/metrics
GET    /api/jobs/<job_id>/findings
GET    /api/jobs/<job_id>/charts   (chart images + captions, the same ones embedded in the report)
GET    /api/jobs/<job_id>/tasks    (the per-agent task trace)
GET    /api/jobs/<job_id>/report?format=html   (also docx, pdf)
DELETE /api/jobs/<job_id>          (deletes the job and everything scoped to it -- documents,
                                     facts, metrics, findings, reports, review items, files)
POST   /api/jobs/<job_id>/instructions   {"content": "..."}   (mid-run steering -- see below)
POST   /api/jobs/<job_id>/assistant      {"message": "...", "auto": false}   (post-hoc, on-demand
                                     agent re-run -- see below)
POST   /api/qa            {"job_id": "...", "question": "What is the current ratio?"}
GET    /api/search?q=...  (the custom web-search tool, see caveat below)
GET    /api/llm/status    (active provider/model, which keys are configured, parallel-call setting)
POST   /api/llm/config    {"openai_api_key": "...", "gemini_api_key": "...", "backend": "auto", "parallel_calls": true}
```

**Talking to the pipeline, not just watching it.** Two distinct, additive mechanisms sit on
top of the fixed data → analysis → delivery sequence (which is unchanged -- see "Scoping
decisions" below for why it's a fixed Celery chain, not a freely-replanned DAG):
- **Mid-run steering** (`POST /api/jobs/<id>/instructions`): extra guidance or data you
  provide *while a job is still running*. There's no live channel into an already-executing
  Celery task, so this is checkpoint-based, not a true interrupt -- the orchestrator picks
  it up at the next stage boundary (`orchestrator.apply_pending_instructions`), decides
  (via an LLM call, not a keyword match) whether it's relevant to that stage's specific
  agents, and if so relays it into their prompts. Shows up as a 🧭 Orchestrator entry in the
  task trace when it's applied.
- **The assistant** (`POST /api/jobs/<id>/assistant`): a chat-driven, on-demand re-run of
  one of the job's own analysis agents against *already-validated* data -- e.g. "redo the
  risk score assuming the one-off item is excluded". If the request could plausibly mean
  more than one agent, the response is `{"type": "clarification", "question", "options"}` --
  pick one and send it back as `{"chosen_agent", "action_note"}` -- unless `"auto": true`,
  in which case the orchestrator just picks its best-ranked option itself. A request that
  doesn't need a re-run at all (a plain lookup) reports `agent_used: null`; the frontend
  falls back to `/api/qa` transparently in that case.

No auth header needed anywhere -- see "No login" above. You can also run
`python gradio_app.py` natively (it needs `API_BASE_URL`, default
`http://localhost:5000/api`, which matches the native setup) for the same UI described in
the Docker quickstart, or `uvicorn frontend_server:app --port 8080` for the plain
HTML/CSS/JS sample frontend (its `API_BASE` is set directly in `frontend/app.js`, not an
env var, since it's static JS running in the browser, not a Python process).

### Tests

```powershell
pytest
```

The test suite (unit tests + `tests/test_pipeline_e2e.py`) runs entirely against the fake
LLM backend and doesn't need Redis/Celery — the e2e test calls the stage supervisors
directly (the same code Celery's tasks invoke), so it proves the whole pipeline is wired
correctly without needing a broker. Swapping in a real LLM only requires the `.env` changes
below; nothing in the pipeline code changes.

Can also run inside the Docker image without a venv: `docker compose run --rm api python -m pytest`
(`python -m pytest`, not bare `pytest` — the module form puts `/app` on `sys.path` so `tests/conftest.py`'s `import app` resolves).

## Switching LLM providers (custom endpoint, OpenAI, Gemini)

`LLM_BACKEND=auto` (the default) picks whichever provider has an API key set, checked in
this order -- **openai, gemini, custom** -- and falls back to the fake backend if none do.
Just paste a key into `.env` (native) or `.env.docker` (Docker Compose), or configure it directly
in the **"LLM & API Keys"** tab in the Gradio web UI (which calls `POST /api/llm/config` --
this writes the key into `current_app.config`/`os.environ` and back out to the `.env`/`.env.docker`
file so it survives a restart, then resets the cached gateway instance so the change takes effect
on the very next LLM call, no redeploy needed). It's used automatically:

```
LLM_BACKEND=auto

# OpenAI (standard + reasoning model)
OPENAI_API_KEY=<your key>
OPENAI_MODEL_NAME=gpt-4o-mini
OPENAI_REASONING_MODEL_NAME=gpt-4o

# Gemini (standard + reasoning model)
GEMINI_API_KEY=<your key>
GEMINI_MODEL_NAME=gemini-2.0-flash
GEMINI_REASONING_MODEL_NAME=gemini-1.5-pro

# Custom endpoint (optional fallback)
LLM_BASE_URL=<your custom endpoint>/v1
LLM_API_KEY=
LLM_MODEL_NAME=custom-model
```

To pin one regardless of which keys are present, set `LLM_BACKEND` explicitly to
`fake` | `real` | `openai` | `openai_reasoning` | `gemini` | `gemini_reasoning` | `reasoning`.

**Model tiering**: agents don't all call the LLM at the same stakes. `BaseAgent.call_llm(...,
tier="reasoning")` routes to the provider's reasoning model (`OPENAI_REASONING_MODEL_NAME` /
`GEMINI_REASONING_MODEL_NAME`) instead of the default one -- used by the analysis modules'
findings, the insight reasoner, the report writer, the verifier, and the QA answer composer,
i.e. everywhere the model is drawing a financial conclusion rather than just classifying or
extracting. Intake classification, schema mapping, and extraction stay on the default
(faster/cheaper) model. `LLM_BACKEND=reasoning` (or `auto_reasoning`) instead pins *every*
call, including those, to the reasoning model.

All three real providers go through the **same** `RealLLMGateway` class
(`app/llm_gateway/client.py`) — OpenAI's API and Gemini's OpenAI-compatibility endpoint
(`https://generativelanguage.googleapis.com/v1beta/openai/`) both speak the same
chat-completions JSON shape a self-hosted endpoint typically does, so provider selection
(`app/llm_gateway/__init__.py::resolve_backend`) is just a different
base_url/api_key/model_name, not different code. If your custom deployment's
request/response shape differs from the OpenAI shape, `client.py` is the only file that
needs to change — every agent talks to the `LLMGateway` interface in
`app/llm_gateway/base.py`, never to the HTTP shape directly. Structured output is handled
by prompting for JSON matching a Pydantic schema and re-asking once on a validation error.

From inside a container, `localhost` means the container itself, not your Windows host —
if a custom endpoint runs on the host, use `http://host.docker.internal:<port>/v1` instead.

Three more knobs (read only by `RealLLMGateway`, so they don't matter for the fake
backend):

```
LLM_PARALLEL_CALLS=true         # false = every call serialized, one at a time, process-wide
LLM_MAX_CONCURRENT_REQUESTS=5   # only matters when LLM_PARALLEL_CALLS=true; per Celery worker PROCESS
LLM_MAX_TOKENS=8192
```

- **`LLM_PARALLEL_CALLS`** is the master switch. `false` forces every LLM call in the whole
  process to be strictly one at a time, no matter how many agents/threads want to call
  concurrently -- for a provider that can't handle overlapping requests at all (this was
  necessary against a small self-hosted deployment, which returned sustained 503s under the
  analysis stage's 5-way fan-out even at low concurrency). `true` allows up to
  `LLM_MAX_CONCURRENT_REQUESTS` calls in flight -- the right setting for OpenAI/Gemini,
  which handle concurrent load fine.
- **`LLM_MAX_CONCURRENT_REQUESTS`** only matters when parallel calls are on. Lower it (2-3)
  if a provider still struggles under load; raise it if it doesn't. `RealLLMGateway._chat`
  also retries transient timeouts/connection errors/5xx twice with backoff before giving up,
  independent of this setting.
- **`LLM_MAX_TOKENS`** matters more for thinking-mode models (e.g. Qwen3 on a custom
  endpoint): they spend part of the budget on a `<think>...</think>` block before the real
  answer, so too low a limit truncates the JSON response mid-string. `client.py` strips
  `<think>` blocks before parsing and auto-retries with a larger budget (x1.5, up to 2 more
  attempts) if the API reports `finish_reason=length`.

## Architecture at a glance

```
API (Flask blueprints, no auth -- single default tenant)
  -> Orchestrator (plan template, DAG, replanning)
    -> Celery task chain: run_data_stage -> run_analysis_stage -> run_delivery_stage
       (each stage's internal fan-out is a ThreadPoolExecutor, not cross-process Celery
       fan-out -- see "Scoping decisions")
       Data stage:      Intake -> Extract (per sheet/table, with header-row detection)
                         -> Map -> Reconcile  (per document, then once)
       Analysis stage:  Ratio&Trend | Cash&WC | Forecast | Risk&Anomaly | GST  (parallel)
       Delivery stage:  Insight -> (Chart spec | Report writer) -> Verifier (<=2 revisions)
  -> QA agent (synchronous, not part of the job DAG)
Tools (deterministic, tool-allowlisted per agent): parsers, table-boundary detection,
  metric registry, ML (forecast/anomaly/risk), sandbox, read-only SQL, web search, vector
  search, chart/report rendering.
Gradio UI (gradio_app.py) and the plain HTML/CSS/JS frontend (frontend/, served by
  frontend_server.py) -> two independent clients, each talking to the API over HTTP only.
```

Every agent implements `TaskSpec -> AgentResult` (`app/agents/base.py`), matching the
design doc's contract, and every tool call goes through `ToolRegistry.invoke`, which
enforces the calling agent's allowlist.

## Scoping decisions vs. the design doc

| Design doc | This build | Why |
|---|---|---|
| Temporal | Celery + Redis, one task per stage, DB-persisted `JobState` for resumability | Full durability with far less deployment surface |
| Cross-process fan-out (queue+DAG engine) per document/module | `ThreadPoolExecutor` inside each stage | Agents are I/O-bound (LLM calls, parsing); true cross-process fan-out added complexity without benefit at this scale |
| Postgres + pgvector + row-level security | SQLite + SQLAlchemy; vector search = stored embeddings (or a local `HashingVectorizer` fallback) + cosine similarity in Python; tenant isolation enforced in the query layer | Matches the chosen DB for local dev |
| OpenTelemetry/Langfuse/Prometheus | Structured logging + `AuditLog`/`TaskRun` tables, queryable via `/api/jobs/<id>/tasks` | Full observability stack is its own project |
| Camelot/Docling/cloud OCR, Prophet/XGBoost, vl-convert, WeasyPrint | pdfplumber + PyMuPDF (+ optional pytesseract), statsmodels ARIMA/ETS, scikit-learn IsolationForest, matplotlib, python-docx + xhtml2pdf | Pure-Python / prebuilt-wheel libraries only — no extra native toolchains to install on Windows (Tesseract for OCR is the one opt-in exception, feature-flagged) |
| gVisor/Firecracker sandbox | Subprocess-based restricted Python exec (blocked imports, timeout) | Crash/runaway protection, not a real security boundary — the code being run is our own analysis agents' output against our own data, not untrusted end-user input |
| OIDC/RBAC | No auth at all -- single fixed default tenant (`app/utils/default_tenant.py`) | This runs as a direct/local application, not a multi-tenant SaaS |
| Text-to-SQL (free-form) | LLM/router picks `{view, filters}` from an allow-listed set; the app composes the actual parameterized SQL | Same "can't escape the allow-list" guarantee with far less validation surface |
| Assumed header row / single table per file | Deterministic header-row detection (`tools/table_detect.py`) with an LLM fallback when metadata precedes the real table; every Excel sheet and every extracted PDF table is processed, not just the first | Real financial files carry metadata above the table and often pack several statements into one workbook/PDF -- confirmed necessary against real-world files, not a hypothetical |

## The web search tool

`app/tools/web_search.py` scrapes Google's results page directly and pulls a short excerpt
from each of the top results, per what was asked for. Worth knowing: this is unofficial
scraping (against Google's ToS for automated querying) and the HTML selectors are
best-effort and will break when Google changes markup — it raises a clear
`WebSearchBlockedError` rather than silently returning garbage when that happens. If
reliability matters, swap `_google_search` for the Custom Search JSON API or a provider
like Tavily/SerpAPI; nothing else in the codebase would need to change.

## Extraction robustness (header detection, multi-sheet/multi-table)

Real financial files rarely start with the data table on line/row 0 -- there's usually a
metadata block above it (company name, report title, "(All amounts in INR Lakhs)") and
sometimes footnotes below. `tools/table_detect.py` runs a deterministic heuristic first
(looks for a row whose neighbor row is clearly numeric data, per column); when that's not
confident, `ExtractorAgent` escalates to a single LLM call (`TableBoundaryResult`, with a
`reasoning` field ordered before the answer so the model has to work through the preview
before committing) rather than silently assuming row 0. Every Excel **sheet** and every
PDF-extracted **table** gets its own detection and its own mapping pass -- a workbook with
P&L/BS/CF as separate sheets is the common case, not an edge case.

Low-confidence *account mappings* and hard *reconciliation* failures (including the
zero-extracted-facts case) both produce `review_items`, but they're not treated the same:
a reconciliation failure halts the job at `AWAITING_REVIEW` for a human to resolve via
`POST /api/review/items/<id>/resolve`, while a low-confidence mapping is auto-approved (job
proceeds, dataset is marked `VALIDATED_WITH_GAPS`) when `AUTO_APPROVE_LOW_CONFIDENCE=true`
(the default) — set it to `false` if you'd rather a human confirm every uncertain mapping
before analysis runs.

A reconciliation failure isn't always a data error, though -- a chart-of-accounts that's a
documented *subset* of Schedule III can't have a named account for every possible caption
(minority interest, share of associates' profit, ...), so a formula like "recomputed PAT =
stated PAT" can legitimately fall short by a bounded amount for a company with more granular
line items than the subset captures. `RECONCILIATION_MATERIALITY_PCT` (default `0.15`, i.e.
15%) auto-approves a reconciliation gap that's smaller than that fraction of the expected
value -- same "log a gap, don't block" treatment as a low-confidence mapping -- while a
larger gap still halts for review, since at that size it's more likely a real mapping/
extraction problem than a schema gap. `NO_FACTS` (an empty dataset) always blocks regardless
of this setting -- there's no "small" version of zero data.

## Grounding: no numbers from "general knowledge"

Every prompt that touches financial figures (`ANALYSIS_MODULE`, `INSIGHT_REASONER`,
`REPORT_WRITER`, `VERIFIER`, `QA_COMPOSER` in `app/llm_gateway/prompts.py`) explicitly
forbids citing a figure, ratio, or benchmark that isn't in the data given to that call --
computed metrics, findings, or search/document excerpts. The model explains what the
*computed* values mean; it never substitutes a remembered or assumed figure for one. This
is on top of, not instead of, the number-binding scheme (§"Report generation" in the
design doc): every number in a report is a `{{m:metric_code:period_end}}` placeholder
resolved from the `metrics` table, and the verifier lints for any raw digit sequence the
model typed directly.

## Repository layout

See `app/` for the package; the structure mirrors the design doc's §12 repo layout
(`agents/`, `tools/`, `orchestrator/`, `llm_gateway/`, `domain/`, `memory/`, `workers/`,
`api/`), adapted for Flask instead of the original FastAPI sketch. `Dockerfile`,
`docker-compose.yml`, `.dockerignore`, and `.env.docker` are the Docker setup described
above; they don't affect the native path (`.env` / `run.py` / native `celery`).
`gradio_app.py` is one UI (its own container in Docker, or run natively with
`python gradio_app.py`) -- it only talks to the Flask API over HTTP, it doesn't import
`app.*` directly. `frontend/` (`index.html`/`style.css`/`app.js`) plus `frontend_server.py`
is the other UI -- a plain HTML/CSS/JS static site (no build step, no framework) served by
a thin FastAPI process; its JS also only talks to the Flask API over HTTP, from the
browser, via CORS.
