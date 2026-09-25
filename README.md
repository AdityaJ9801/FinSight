# FinSight — Multi-Agent Financial Analysis Platform

FinSight is an end-to-end, multi-agent financial analysis platform that ingests unstructured and structured corporate financial documents (P&L, Balance Sheet, Cash Flow Statement, Bank Statements, and GST Returns) in Excel/CSV/PDF formats — including multi-sheet workbooks and files with metadata headers — extracts and reconciles them into an immutable ledger, computes standardized financial ratios, executes ML anomaly/risk/forecast analysis, and generates publication-grade executive reports with interleaved visualizations and an interactive Virtual CFO diagnostic Q&A assistant.

Two interfaces access the Flask API over HTTP:
1. **Interactive Web Application** (`frontend/`, served by `frontend_server.py` at `http://localhost:8080`): A zero-build, responsive web application for document upload, real-time agent execution tracking, human-in-the-loop review & approval, interactive report reading with embedded charts, and multi-turn Virtual CFO chat.
2. **RESTful API** (`app/api/` at `http://localhost:5000/api`): Comprehensive endpoints for automated workflows, agent steering, job control, and data export.

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

---

## Quickstart — Docker (Recommended)

This is the easiest way to run the entire platform (Flask API + Celery Worker + Redis + Web Frontend) with a single command. Requires Docker Desktop.

```powershell
copy .env.docker.example .env.docker
docker compose up --build
```

`.env.docker` defaults to `LLM_BACKEND=fake`, enabling full end-to-end testing before adding real LLM credentials.

This builds the unified Docker image, starts Redis, executes the database initialization container (`flask init-db`), and starts:
- **Flask API**: `http://localhost:5000`
- **Modern Web Application**: `http://localhost:8080`
- **Celery Worker**: Background task executor connected to Redis.

Open **`http://localhost:8080`** in your browser:
1. **Run Analysis**: Upload sample files from `seed/data/` (e.g. `balance_sheet.csv`, `pnl.csv`, `cash_flow.csv`) or `seed/data/multi_sheet_statements.xlsx`, and click **Run Pipeline**.
2. **Watch Live Trace**: Watch real-time execution across Intake, Extractor, Mapper, Reconciler, Analysis, Insight, Chart Spec, Report Writer, and Verifier agents.
3. **Review & Approve**: Handle reconciliation discrepancies or low-confidence mappings.
4. **Results**: Inspect metrics, findings, and the rendered executive report (HTML, DOCX, PDF).
5. **Ask a Question**: Query the Virtual CFO assistant for figures, visual charts, or reverse-flow root-cause diagnostics.

Command line test run from a second terminal:
```powershell
python seed/upload_demo_job.py
```

To stop containers: `docker compose down` (persists data in volume) or `docker compose down -v` (wipes data for a clean slate).

---

## Quickstart — Native (Windows / macOS / Linux)

### 1. Environment Setup
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
flask init-db
```

### 2. Start Services
Requires Redis running on `localhost:6379` (`docker run -d -p 6379:6379 redis:alpine`).

In separate terminals:
```powershell
# Terminal 1: Celery Worker (--pool=solo required on Windows)
celery -A app.workers.celery_app worker --pool=solo -l info

# Terminal 2: Flask API Backend
python run.py

# Terminal 3: Web Application Frontend
uvicorn frontend_server:app --port 8080
```

Open `http://localhost:8080` to access the application.

---

## Testing

```powershell
pytest
```

The test suite runs against a deterministic fake LLM gateway without requiring external API credentials or a running Redis broker:
- **57 unit and integration tests** covering document parsing, table detection, accounting reconciliation, metric computation, agent workflows, Virtual CFO diagnostic compendium, and end-to-end report generation.

Inside Docker:
```powershell
docker compose run --rm api python -m pytest
```

---

## API Endpoints

```
# Jobs & Execution
POST   /api/jobs                         Create job and upload financial documents
GET    /api/jobs/<job_id>                Get job execution status and stage progress
GET    /api/jobs/<job_id>/tasks          Per-agent execution trace (timing, confidence, status)
POST   /api/jobs/<job_id>/instructions   Mid-run steering instruction for upcoming stage
POST   /api/jobs/<job_id>/assistant      Post-analysis chat assistant (on-demand agent re-runs)
DELETE /api/jobs/<job_id>                Delete job and all associated facts, reports, and files

# Financial Results & Artifacts
GET    /api/jobs/<job_id>/metrics        Computed financial ratios and time-series
GET    /api/jobs/<job_id>/findings       Analysis findings across Ratio, Cash/WC, Forecast, Risk, GST
GET    /api/jobs/<job_id>/charts         Visual chart specifications and PNG images
GET    /api/jobs/<job_id>/report         Rendered executive report (format=html|docx|pdf)

# Human-in-the-Loop Review
GET    /api/review/items                 List pending review items
POST   /api/review/items/<id>/resolve    Approve or adjust low-confidence mapping / reconciliation gap

# Virtual CFO Interactive Q&A
POST   /api/qa                           Query ledger figures, visual charts, or root-cause diagnostics

# LLM Gateway Configuration
GET    /api/llm/status                   Current provider, model tier, and configured keys
POST   /api/llm/config                   Update LLM backend and API keys at runtime
```

---

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
  ├── Orchestrator (DAG planning, stage gating, checkpoint-based instruction injection)
  │     │
  │     ├── Stage 1: Data Processing
  │     │     ├── IntakeAgent (document classification)
  │     │     ├── ExtractorAgent (table boundary detection, multi-sheet extraction)
  │     │     ├── MapperAgent (Chart of Accounts semantic mapping)
  │     │     └── ReconcilerAgent (cross-statement consistency checks)
  │     │
  │     ├── Stage 2: Parallel Financial Analysis
  │     │     ├── RatioAnalysisAgent (liquidity, leverage, profitability, efficiency)
  │     │     ├── CashWorkingCapitalAgent (cash conversion cycles, working capital)
  │     │     ├── ForecastAgent (trend extrapolation, ARIMA/ETS projections)
  │     │     ├── RiskAnomalyAgent (IsolationForest outlier detection, red flags)
  │     │     └── GSTReconciliationAgent (turnover & ITC reconciliation)
  │     │
  │     └── Stage 3: Executive Delivery
  │           ├── InsightReasonerAgent (ranked executive takeaways)
  │           ├── ChartSpecAgent (matplotlib visual generation)
  │           ├── ReportWriterAgent (deterministic taxonomy skeleton, diagnostic guides)
  │           └── VerifierAgent (number safety checks, placeholder verification)
  │
  ├── Virtual CFO QAAgent (synchronous 5-point reverse-flow diagnostic answering)
  │     └── 40-Metric Financial Intelligence Flowchart Engine
  │
  └── Tool Registry (allowlisted tool invocation per agent):
        Parsers, Table Boundary Detection, Metrics Registry, ML Sandbox,
        Read-only SQL, Vector Search, Web Search, Report Renderers (HTML/DOCX/PDF).
```

---

## Repository Layout

```
├── app/
│   ├── agents/
│   │   ├── data/             # Intake, Extractor, Mapper, Reconciler
│   │   ├── analysis/         # Ratio, Cash/WC, Forecast, Risk, GST
│   │   └── delivery/         # Insight, ChartSpec, ReportWriter, Verifier, QAAgent
│   ├── api/                  # Flask REST blueprints (jobs, review, results, qa, llm)
│   ├── domain/               # Chart of Accounts, Taxonomy, 40-metric Virtual CFO Compendium
│   ├── llm_gateway/          # Unified LLM client (OpenAI, Gemini, Custom, Fake)
│   ├── memory/               # Historical mapping memory
│   ├── models/               # SQLAlchemy models (Job, Document, Account, Metric, Report)
│   ├── orchestrator/         # DAG coordinator, stage gates, instruction steering
│   ├── tools/                # Deterministic tools (parsers, metrics, ML, renderers)
│   └── workers/              # Celery application and task definitions
├── frontend/                 # Responsive web application (HTML/CSS/JS)
├── frontend_server.py        # Static web server (FastAPI/Uvicorn)
├── seed/                     # Sample data (P&L, Balance Sheet, Cash Flow, Multi-sheet Excel)
├── tests/                    # 57 automated unit and integration tests
├── Dockerfile                # Production container specification
├── docker-compose.yml        # Multi-service stack (API, Worker, Redis, Frontend)
├── requirements.txt          # Python dependencies
└── run.py                    # Flask development server entrypoint
```

---

## License

Apache 2.0. See LICENSE for details.
