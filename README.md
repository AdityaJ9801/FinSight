# FinSight — Multi-Agent Financial Analysis Platform

![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Tests](https://img.shields.io/badge/tests-89%20passing-brightgreen.svg)
![Docker](https://img.shields.io/badge/docker-ready-blue.svg)

FinSight is an end-to-end, multi-agent financial analysis platform that ingests unstructured and structured corporate financial documents (P&L, Balance Sheet, Cash Flow Statement, Bank Statements, and GST Returns) in Excel/CSV/PDF formats — including multi-sheet workbooks and files with metadata headers — extracts and reconciles them into an immutable ledger, computes standardized financial ratios, executes ML anomaly/risk/forecast analysis, and generates publication-grade executive reports with interleaved visualizations and an interactive Virtual CFO diagnostic Q&A assistant.

Two interfaces access the Flask API over HTTP:
1. **Web Application** (`frontend/`, React + TypeScript + Vite; a static site; in Docker, nginx serves it at `http://localhost:8080` and forwards `/api` to Flask): upload, a live run log of every agent, human-in-the-loop review, an overview with a summary opinion, key ratios, health rating, peer benchmarks and findings, the verified report, charts, detailed statement analysis, side-by-side comparison of analyses, and a chat panel that guides a running analysis or answers questions about a finished one.
2. **RESTful API** (`backend/app/api/` at `http://localhost:5000/api`): Comprehensive endpoints for automated workflows, agent steering, job control, and data export.

**No login required for local execution.** Designed as a direct application where all requests resolve to a default tenant/entity (`app/utils/default_tenant.py`), while preserving multi-tenant database schemas under the hood.

---

### Key Capabilities & Architectural Innovations

- 🧠 **Virtual CFO Financial Intelligence Engine** (`app/domain/financial_intelligence.py`):
  Comprehensive diagnostic knowledge base modeling **40 core financial metrics** across an exhaustive **6-level reverse-flow drill-down**:
  1. *Formula*: Governing mathematical equation.
  2. *Governing Components*: Structural balance sheet / P&L components.
  3. *Operational Drivers*: Real-world business operations driving financial results.
  4. *Root Causes*: Underlying reasons for change (mix shifts, commodity cycles, bottlenecks, leakage).
  5. *What to Investigate*: Concrete operational data, sub-meters, logs, and aging ledgers.
  6. *What to Ask Management*: High-impact CFO questions and strategic action points.
  Answers automated reverse-flow diagnostic queries: *What changed? Why did it change? What caused it? What to investigate? What to ask management?*

- 📊 **Deterministic Report Redesign & Executive Visual Layer** (`app/domain/taxonomy.py`, `app/tools/report_render.py`):
  - **Taxonomy-Anchored Skeletons**: Reports follow a predictable, ordered structure (`build_report_skeleton()`) anchored in verified data rather than LLM improvisation.
  - **Interleaved Chart Embeddings**: High-resolution trend visualizations are seamlessly embedded directly into their corresponding narrative domain sections.
  - **Executive Presentation Layer**: Premium cover banner, composite financial health score indicator, and executive KPI performance overview grid — fully cross-compatible with HTML, DOCX, and PDF (xhtml2pdf compliant).
  - **Strict Number Safety**: Every financial metric is bound via a `{{m:metric_code:period_end}}` placeholder against the database; direct typing of unverified digits is blocked by automated linting.

- 💬 **Interactive Chat Assistant & Reverse-Flow Q&A** (`app/agents/delivery/qa.py`, `app/api/qa.py`):
  - **Diagnostic Routing**: Automatically identifies diagnostic queries (*"Why did EBITDA margin decline?"*, *"What caused current ratio to drop?"*) and generates structured 5-point Virtual CFO reverse-flow diagnostic traces.
  - **Multi-Turn Conversation Memory**: Tracks conversation history across turns in the interactive chat assistant.
  - **On-Demand Delivery Agent Re-Runs**: Users can steer or re-run delivery agents (`report_writer`, `insight_reasoner`, `chart_spec`) from chat, auto-regenerating verified reports and visual artifacts.
  - **Visual Chart Q&A**: Dedicated `chart_lookup` route explains visual trend graphs and cost breakdowns.

- 🧮 **Detailed Statement Analysis** (`app/tools/calc/detailed_analysis.py`, `app/agents/analysis/detailed_analytics.py`):
  horizontal (YoY) and common-size analysis of every statement line, DuPont decomposition of ROE, CAGR of
  revenue/EBITDA/PAT/assets, a PAT bridge (profit walk) that always foots, working capital / net debt /
  net-debt-to-EBITDA, and bank cash-flow analytics (monthly flows, counterparty concentration). Its metrics feed
  the narrative through placeholders like every other module, and the report adds a deterministic
  *Supporting Tables* section (HTML, DOCX, PDF).

- 📈 **Decision-grade charts** (`app/agents/delivery/chart_spec.py`, `app/tools/chart_render.py`): 16 charts, each placed in its report section, with readable labels, unit-aware axes (%, x, days, Rs in lakh/crore), data labels, benchmark lines (e.g. current ratio 1.0x / 1.33x, coverage floor 1.5x) and a computed one-line takeaway — health scorecard, revenue/EBITDA/margin combo, margin profile, where each rupee of income goes, liquidity vs benchmarks, leverage & debt service, working-capital cycle, cash-flow profile, YoY growth, returns & asset efficiency, forecast with uncertainty band, PAT bridge, DuPont, balance-sheet structure, monthly bank flows and counterparty concentration.

- 🧩 **Registry-driven multi-agent structure** (`app/agents/registry.py`, `app/orchestrator/executor.py`, `app/orchestrator/blackboard.py`):
  - **Agent registry**: one declaration per agent (stage, dependencies, description, steerable/re-runnable) drives the orchestrator's routing prompt, the chat assistant's re-run options, plan templates and the web UI (`GET /api/agents`).
  - **DAG executor**: each stage runs its agents as a dependency graph — independent agents overlap, dependents start as soon as their inputs exist, and a failing node is captured instead of sinking the stage.
  - **Job blackboard**: agents publish and consume named artifacts (`insights`, `charts`, `draft`, `forecast`, `detailed_analysis`) instead of hard-coded file paths.

---

## Quickstart — Docker (Recommended)

Runs everything (Flask API, Celery worker, Redis, web app) with one command. Requires Docker Desktop.

```powershell
copy backend\.env.docker.example backend\.env.docker
docker compose up --build
```

`.env.docker` defaults to `LLM_BACKEND=fake`, so the whole pipeline runs before you add real LLM credentials.
Compose builds the two images (`backend/` and `frontend/`), starts Redis, runs `flask init-db` once, and starts:
- **Web application**: `http://localhost:8080` (nginx, forwards `/api` to the API)
- **Flask API**: `http://localhost:5000`
- **Celery worker**: runs the analysis pipeline

Open **`http://localhost:8080`**, click **Use sample statements** (or upload your own), and start an analysis.

To stop: `docker compose down` (keeps data) or `docker compose down -v` (wipes it).

---

## Quickstart — Native (Windows / macOS / Linux)

### 1. Backend setup
```powershell
python -m venv .venv
.venv\Scripts\activate
cd backend
pip install -r requirements.txt
copy .env.example .env
flask init-db
```

### 2. Start the services
Requires Redis on `localhost:6379` (`docker run -d -p 6379:6379 redis:alpine`). In separate terminals:
```powershell
# Terminal 1 (in backend/): Celery worker (--pool=solo is required on Windows)
celery -A app.workers.celery_app worker --pool=solo -l info

# Terminal 2 (in backend/): Flask API on :5000
python run.py

# Terminal 3 (in frontend/): web app
npm ci
npm run dev        # http://localhost:5173, hot reload
# or, the production build: npm run build && npm run preview   (http://localhost:8080)
```

Both `npm run dev` and `npm run preview` forward `/api` to the backend on `:5000`.

---

## Testing

```powershell
cd backend
pytest
```

The suite runs against a deterministic fake LLM gateway, with no API credentials or Redis broker needed. It
covers document parsing, table detection, reconciliation, metric computation, agent workflows, the DAG executor
and agent registry, detailed analytics, charts, bank-statement-only analyses, peer benchmarks, the web API, the
Virtual CFO compendium and end-to-end report generation.

Frontend type check: `cd frontend && npm run typecheck`.

Inside Docker:
```powershell
docker compose run --rm api python -m pytest
```

---

## Deployment

`backend/` and `frontend/` are independent, so they can be deployed together or separately.

**Everything on one server:** `docker compose up -d --build`. Put a TLS-terminating proxy in front of port 8080.

**Separately**, for example the backend on Render, Railway or a VM, and the frontend on Vercel or Netlify:

| | Backend (`backend/`) | Frontend (`frontend/`) |
|---|---|---|
| Build | `backend/Dockerfile` | `npm ci && npm run build` (output `dist/`), or `frontend/Dockerfile` |
| Run | API: image default (gunicorn on `$PORT`, default 5000). Worker: `celery -A app.workers.celery_app worker -l info`. Once per release: `flask init-db` | Static files; `vercel.json` / `public/_redirects` handle client-side routes |
| Config | Environment from `backend/.env.example` (`CELERY_BROKER_URL` must point at your Redis) | `VITE_API_BASE=https://<your-backend>/api` at build time |
| Storage | Persist `/app/instance` (SQLite database and uploaded files), or set `DATABASE_URL` / `STORAGE_ROOT` | none |

The API allows cross-origin requests, so a frontend on its own domain works without extra setup. With the
`frontend/Dockerfile` (nginx), set `API_URL` to the backend's address instead and leave `VITE_API_BASE` unset.

---

## API Endpoints

```
# Jobs & Execution
GET    /api/jobs                         List jobs, newest first, with document counts and company profile
POST   /api/jobs                         Create job and upload financial documents (optional company_name, industry)
POST   /api/jobs/<job_id>/documents      Add statements to a finished analysis; re-runs it into a new dataset version
PUT    /api/jobs/<job_id>/profile        Set the company name and industry (used for comparison and benchmarks)
GET    /api/jobs/<job_id>                Get job execution status and stage progress
GET    /api/jobs/<job_id>/tasks          Per-agent execution trace (timing, confidence, status)
POST   /api/jobs/<job_id>/instructions   Mid-run steering instruction for upcoming stage
POST   /api/jobs/<job_id>/assistant      Post-analysis chat assistant (on-demand agent re-runs)
DELETE /api/jobs/<job_id>                Delete job and all associated facts, reports, and files

# Financial Results & Artifacts
GET    /api/jobs/<job_id>/metrics        Computed financial ratios and time-series
GET    /api/jobs/<job_id>/findings       Analysis findings across Ratio, Cash/WC, Forecast, Risk, GST
GET    /api/jobs/<job_id>/health         Rules-based health score over each metric's latest period
GET    /api/jobs/<job_id>/benchmarks     Latest ratios placed in industry quartiles (?industry= to override)
GET    /api/benchmarks/industries        Industries with benchmark data, and the data source
GET    /api/jobs/<job_id>/charts         Visual chart specifications and PNG images
GET    /api/jobs/<job_id>/report         Rendered executive report (format=html|docx|pdf)

# Human-in-the-Loop Review
GET    /api/review/items                 List pending review items
POST   /api/review/items/<id>/resolve    Approve or adjust low-confidence mapping / reconciliation gap

# Detailed Analysis & Agents
GET    /api/jobs/<job_id>/analysis       Detailed statement analysis (YoY, common-size, DuPont, CAGR, profit bridge, bank)
GET    /api/agents                       Agent registry: stages, dependencies, descriptions

# Virtual CFO Interactive Q&A
POST   /api/qa                           Query ledger figures, visual charts, or root-cause diagnostics

# LLM Gateway Configuration
GET    /api/llm/status                   Current provider, model tier, and configured keys
POST   /api/llm/config                   Update LLM backend and API keys at runtime
```

---

## Peer Benchmarks

`app/domain/benchmarks.py` ships **indicative** quartile ranges (p25 / median / p75) for ten Indian sectors so
the feature works out of the box. They are not a licensed dataset. To use your own (for example CMIE Prowess, or
an internal loan-book study), point `BENCHMARKS_FILE` at a JSON file of the same shape; it replaces the built-in
table and its `source` / `as_of` are shown in the UI:

```json
{"source": "CMIE Prowess", "as_of": "FY2024",
 "industries": {"manufacturing": {"label": "Manufacturing", "metrics": {"current_ratio": [1.1, 1.45, 1.9]}}}}
```

Percentage ratios are fractions (`0.12` = 12%), coverage ratios are multiples, and working-capital metrics are days.

## Upgrading an Existing Database

Run `flask init-db` once after pulling (it only creates what's missing, so it's safe on existing data). The API also
creates the `job_profiles` table on startup if it's missing.

## Switching LLM Providers

`LLM_BACKEND=auto` (default) automatically uses whichever provider has an API key configured in `.env` (or via the **LLM & API Keys** tab in the web UI):
1. **OpenAI**: `OPENAI_API_KEY`, models `gpt-4o-mini` (default) and `gpt-4o` (reasoning tier).
2. **Google Gemini**: `GEMINI_API_KEY`, models `gemini-2.0-flash` (default) and `gemini-1.5-pro` (reasoning tier).
3. **Custom Local / vLLM Endpoint**: `LLM_BASE_URL`, `LLM_MODEL_NAME`.
4. **Offline Mock**: `LLM_BACKEND=fake` (deterministic stand-in for testing).

---

## Architecture

```
Client (Web UI at :8080 or REST API at :5000)
  │
  ▼
Flask API Layer
  │
  ├── Orchestrator (plan templates, stage gating, checkpoint-based instruction injection)
  │     │   Agent Registry: one declaration per agent -> routing, templates, assistant, UI
  │     │   Blackboard: named job artifacts (insights, charts, draft, forecast, detailed_analysis)
  │     │   DAG Executor: runs each stage's agents by dependency, in parallel where possible
  │     │
  │     ├── Stage 1: Data Processing
  │     │     ├── IntakeAgent (document classification)
  │     │     ├── ExtractorAgent (table boundary detection, multi-sheet extraction)
  │     │     ├── MapperAgent (Chart of Accounts semantic mapping)
  │     │     └── ReconcilerAgent (cross-statement consistency checks)
  │     │
  │     ├── Stage 2: Parallel Financial Analysis
  │     │     ├── RatioTrendAgent (liquidity, leverage, profitability, efficiency)
  │     │     ├── CashWorkingCapitalAgent (cash conversion cycles, working capital)
  │     │     ├── ForecastAgent (trend extrapolation, ETS projections on the fiscal calendar)
  │     │     ├── RiskAnomalyAgent (IsolationForest outlier detection, red flags)
  │     │     ├── GstComplianceAgent (turnover & ITC reconciliation)
  │     │     └── DetailedAnalyticsAgent (YoY/common-size, DuPont, CAGR, profit bridge, bank flows)
  │     │
  │     └── Stage 3: Executive Delivery (DAG)
  │           ├── InsightReasonerAgent ─┐
  │           └── ChartSpecAgent ───────┴─> ReportWriterAgent -> VerifierAgent (revision loop)
  │                 └──> Publish: narrative + Detailed Statement Analysis tables + Data Diagnostic
  │                      rendered to HTML / DOCX / PDF
  │
  ├── Virtual CFO QAAgent (synchronous 5-point reverse-flow diagnostic answering)
  │     └── 40-Metric Financial Intelligence Flowchart Engine
  │
  └── Tool Registry (allowlisted tool invocation per agent):
        Parsers, Table Boundary Detection, Metrics Registry, ML Sandbox, Read-only SQL,
        Vector Search, Web Search, Detailed Statement Analytics,
        Report Renderers (HTML/DOCX/PDF).
```

---

## Repository Layout

```
├── backend/                  # Flask API + Celery worker (deploy on its own)
│   ├── app/
│   │   ├── agents/           # data/, analysis/, delivery/ agents and the agent registry
│   │   ├── api/              # REST blueprints (jobs, review, results, qa, llm, agents, benchmarks)
│   │   ├── domain/           # Chart of accounts, taxonomy, Virtual CFO compendium, benchmarks
│   │   ├── llm_gateway/      # Unified LLM client (OpenAI, Gemini, custom, fake)
│   │   ├── models/           # SQLAlchemy models
│   │   ├── orchestrator/     # Stage coordinator, DAG executor, blackboard, instruction steering
│   │   ├── tools/            # Deterministic tools (parsers, metrics, analysis, ML, renderers)
│   │   └── workers/          # Celery application and tasks
│   ├── seed/                 # Sample statements
│   ├── tests/                # Automated tests
│   ├── Dockerfile            # API/worker image (gunicorn)
│   ├── requirements.txt
│   └── run.py                # App entrypoint (python run.py for local development)
├── frontend/                 # React + TypeScript + Vite web app (deploy on its own)
│   ├── src/                  # Pages, components, API client
│   ├── Dockerfile            # Build + nginx image
│   ├── nginx.conf.template   # SPA routing and /api forwarding
│   └── vercel.json           # Static-host routing (Netlify: public/_redirects)
└── docker-compose.yml        # Whole stack: Redis, init, API, worker, web
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch conventions, test requirements, and PR guidelines.

---

## License

Apache 2.0. See [LICENSE](LICENSE) for details.
