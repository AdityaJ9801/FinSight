# FinSight — Project Submission

> Complete submission reference for the IBM Call for Code / IBM Bob hackathon entry.
> All fields below map directly to the submission form sections.

---

## 📋 Basic Information

### Project Title
**FinSight — Multi-Agent Financial Analysis Platform**

### Short Description
FinSight is an AI-powered, multi-agent platform that transforms raw corporate financial documents into boardroom-ready executive reports, interactive Power BI models, and a live Virtual CFO diagnostic assistant — in minutes, not days.

### Long Description
FinSight ingests unstructured and structured corporate financial documents (P&L, Balance Sheet, Cash Flow Statement, Bank Statements, and GST Returns) in Excel/CSV/PDF formats — including multi-sheet workbooks and files with metadata headers — extracts and reconciles them into an immutable double-entry ledger, computes 40 standardised financial ratios, executes ML anomaly/risk/forecast analysis, and generates publication-grade executive reports with interleaved charts plus an interactive Virtual CFO diagnostic Q&A assistant.

**Why it matters:** Finance teams spend 60–80% of their analysis time on data wrangling and formatting. FinSight eliminates that entirely. A CFO uploads three CSVs and receives a verified, auditable, board-ready report within minutes — complete with Power BI desktop models and a chat assistant that answers root-cause questions with a structured 5-point reverse-flow diagnostic trace (*What changed → Why → Root cause → What to investigate → What to ask management*).

**Key innovations:**
- **Multi-agent DAG orchestration**: 13 specialised agents across 3 pipeline stages run as a dependency graph — independent agents execute in parallel, dependents start the moment their inputs are ready.
- **Virtual CFO Financial Intelligence Engine**: A 40-metric, 6-level reverse-flow diagnostic compendium turns a vague question like *"Why did EBITDA margin drop?"* into a structured boardroom-quality answer.
- **Taxonomy-anchored reporting**: Reports follow a deterministic skeleton anchored in verified database values — LLM improvisation of financial figures is structurally blocked by a `{{m:metric_code}}` placeholder-binding system.
- **Power BI integration (zero-credential)**: Every job exports a fully self-contained `.pbip` project (star schema, 66 DAX measures, 6-page report) that opens in Power BI Desktop with no gateway or data source required. Optional service-principal publishing ties out headline DAX measures against the ledger before going live.
- **Human-in-the-loop review**: Low-confidence account mappings and reconciliation gaps surface as actionable review items; users approve or adjust before the pipeline continues.

**Technology stack:** Python · Flask · Celery · Redis · SQLite/PostgreSQL · scikit-learn · pandas · OpenAI / Google Gemini / custom LLM endpoints · Power BI REST API · Docker.

### IBM Bob Usage Statement
IBM Bob was the AI coding assistant used throughout the entire development lifecycle of FinSight:

- **Architecture & System Design**: Bob guided the design of the multi-agent DAG architecture, blackboard pattern, agent registry, and the three-stage pipeline topology from first principles.
- **Agent Implementation**: All 13 agent classes (Intake, Extractor, Mapper, Reconciler, RatioTrend, CashWC, Forecast, RiskAnomaly, GST, DetailedAnalytics, InsightReasoner, ChartSpec, ReportWriter, PowerBIPublisher, QAAgent, Verifier) were scaffolded, iteratively refined, and debugged with Bob.
- **Financial Intelligence Engine**: The 40-metric, 6-level reverse-flow diagnostic compendium (`app/domain/financial_intelligence.py`) was built in an extended Bob session, mapping each metric to its formula, governing components, operational drivers, root causes, investigation targets, and management questions.
- **Power BI Integration**: The star-schema semantic model, 66 DAX measures, PBIR JSON project structure, and REST-API publish/verify flow were all developed through Bob task sessions.
- **Test Suite**: All 85 automated unit and integration tests — including fake-LLM gateway, in-process Power BI mock, accounting reconciliation checks, and DAG executor tests — were written with Bob.
- **Frontend & API**: The responsive zero-build web application (`frontend/`), Flask REST API blueprints, and real-time agent execution tracking were built using Bob.
- **Documentation**: This README, SUBMISSION.md, and all inline code documentation were drafted and refined with Bob.

Bob session screenshots are included in the `/docs/bob-sessions/` folder of the repository.

### Technology & Category Tags
`artificial-intelligence` · `multi-agent-systems` · `financial-analysis` · `ibm-bob` · `python` · `flask` · `power-bi` · `llm` · `openai` · `google-gemini` · `machine-learning` · `docker` · `celery` · `redis` · `data-visualization` · `natural-language-processing` · `call-for-code`

---

## 💻 Application & Code

### Public Code Repository
`https://github.com/<your-org>/finsight` *(update with actual URL before submission)*

### IBM Bob Task Session Summary Screenshots
Capture screenshots directly from the IBM Bob interface during your session and upload them to the submission form.

Suggested moments to capture (one screenshot each):
- Designing the DAG orchestrator + agent registry
- Writing an agent class with tools and blackboard publish
- Building the 40-metric Financial Intelligence compendium
- Writing Power BI DAX measures and star-schema tables
- Generating the 85-test suite (show green test run)
- Building the frontend polling loop + Flask API blueprint

### Demo Application Platform
Docker / Self-hosted (Linux, macOS, Windows via Docker Desktop)

### Application URL
`http://localhost:8080` (local Docker deployment)

Public demo URL: *(to be added — deploy to a cloud VM or IBM Code Engine before submission)*

---

## 📸 Media & Presentation

### Cover Image
`docs/media/cover.html` → export as `docs/media/cover.png`
- Dimensions: 1280 × 720 px (16:9) — fixed in the HTML `<body>` style
- Open `cover.html` in Chrome → right-click → **Save as image**, or use DevTools **Capture screenshot**
- Shows: FinSight brand, 4 feature callouts, live agent trace panel, KPI grid, Virtual CFO chat bubble, tech stack bar

### Video Demonstration
`docs/media/demo.mp4` *(to be recorded — see script below)*

**Demo script (≈3 min):**
1. **[0:00–0:20]** Open `http://localhost:8080`. Show the clean upload interface.
2. **[0:20–0:50]** Upload `seed/data/balance_sheet.csv`, `pnl.csv`, `cash_flow.csv`. Click **Run Pipeline**. Watch the live agent execution trace — 13 agents across 3 stages with real-time status badges.
3. **[0:50–1:30]** Pipeline completes. Open the **Executive Report** tab — show the cover banner, financial health score, KPI grid, narrative sections, and interleaved trend charts.
4. **[1:30–2:00]** Switch to **Power BI** tab. Click **Download .pbip project**. Briefly show the 66 DAX measures and 6-page report structure.
5. **[2:00–2:40]** Open **Virtual CFO** chat. Ask: *"Why did the current ratio decline?"* — show the structured 5-point reverse-flow diagnostic response.
6. **[2:40–3:00]** Mention Docker single-command setup, 85 automated tests, and IBM Bob usage throughout development.

### Slide Presentation
`docs/media/slides.pdf` *(see `SLIDES.md` for the full slide-by-slide outline)*

---

## 🔗 Quick Reference

| Item | Location |
|---|---|
| Submission form fields | This file (`SUBMISSION.md`) |
| Full technical README | `README.md` |
| Apache 2.0 License | `LICENSE` |
| Slide outline | `SLIDES.md` |
| Contributing guide | `CONTRIBUTING.md` |
| Cover image (HTML source) | `docs/media/cover.html` |
| Cover image brief | `docs/media/cover-design-brief.md` |
| Demo video script | This file (§ Video Demonstration) |
| Sample data for demo | `seed/data/` |
| Docker quickstart | `README.md` § Quickstart — Docker |
