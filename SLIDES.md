# FinSight — Slide Presentation Outline

> Use this outline to build `docs/media/slides.pdf` (PowerPoint / Google Slides / Canva).
> Target: **8–10 slides**, ≤ 3 min spoken delivery.

---

## Slide 1 — Title

**FinSight**
*Multi-Agent Financial Analysis Platform*

Subtitle: *From raw spreadsheets to boardroom-ready intelligence in minutes*

Visual: Clean hero graphic — document upload → pipeline → executive report

---

## Slide 2 — The Problem

**Finance teams spend 60–80% of their time on data wrangling**

- Manually copying figures from Excel to Word
- No consistent metric definitions across reports
- Root-cause questions answered by instinct, not structured analysis
- Power BI models built by hand for each client

Visual: Timeline showing "Days of manual work" vs "FinSight: minutes"

---

## Slide 3 — Solution Overview

**FinSight: Three stages, 13 agents, one click**

```
Upload Documents
      ↓
Stage 1: Data Processing (Intake → Extract → Map → Reconcile)
      ↓
Stage 2: Financial Analysis (Ratios, Cash/WC, Forecast, Risk, GST, BI)
      ↓
Stage 3: Delivery (Insight + Charts + Power BI → Report → Verify)
      ↓
Executive Report  |  Power BI .pbip  |  Virtual CFO Chat
```

---

## Slide 4 — Key Innovation 1: Virtual CFO Engine

**"Why did EBITDA margin drop?" — answered in 5 structured points**

1. *What changed* — EBITDA margin fell 4.2 pp YoY
2. *Why it changed* — Revenue grew 8%, but COGS grew 17%
3. *Root cause* — Raw material cost spike + logistics surcharge
4. *What to investigate* — Supplier invoices, freight log, inventory aging
5. *What to ask management* — "Have you locked in forward contracts?"

Built on a **40-metric, 6-level diagnostic compendium** — no hallucinated figures

Visual: Screenshot of Virtual CFO chat panel

---

## Slide 5 — Key Innovation 2: Taxonomy-Anchored Reports

**LLM improvisation of financial figures is structurally blocked**

- Report skeleton driven by `taxonomy.py` — deterministic, ordered, reproducible
- Every number bound via `{{m:metric_code:period}}` placeholder resolved from the verified ledger
- Automated linting rejects drafts containing unverified numeric literals
- Output: HTML · DOCX · PDF — all identical, all auditable

Visual: Side-by-side of placeholder draft and rendered report section

---

## Slide 6 — Key Innovation 3: Power BI Integration

**Publication-grade Power BI output with zero configuration**

- Star schema (9 tables, 4 relationships) auto-built for every job
- **66 DAX measures** restate the same formulas as Python — numbers always tie out
- 6-page PBIR report: Executive Overview, Horizontal/Common-Size, Ratios/DuPont/Growth, Profit Bridge, Cash & Bank, Findings
- Download `.pbip` → open in Power BI Desktop → click Refresh → done
- Optional service-principal auto-publish with DAX tie-out verification

Visual: Power BI Desktop screenshot showing the model and a report page

---

## Slide 7 — Architecture

```
Web UI (:8080)  /  REST API (:5000)
          ↓
    Flask API Layer
          ↓
  Orchestrator (DAG Executor + Blackboard + Agent Registry)
    ├── Stage 1: Data       [Intake, Extractor, Mapper, Reconciler]
    ├── Stage 2: Analysis   [Ratio, Cash/WC, Forecast, Risk, GST, BI]
    └── Stage 3: Delivery   [Insight, ChartSpec, PowerBI, Writer, Verifier]
          ↓
  Celery Worker (async) · Redis · SQLite / PostgreSQL
```

**13 agents · 85 automated tests · Docker single-command deploy**

---

## Slide 8 — Built with IBM Bob

**IBM Bob powered the entire development lifecycle**

| What | How Bob helped |
|---|---|
| System design | DAG architecture, blackboard, registry |
| 13 agent classes | Scaffolding, iteration, debugging |
| Financial Intelligence | 40-metric diagnostic compendium |
| Power BI model | Star schema, 66 DAX measures, REST flow |
| 85 tests | Unit, integration, fake-LLM, BI mock |
| Frontend + API | Web app, REST blueprints, real-time trace |

Visual: IBM Bob logo + screenshot of a Bob task session

---

## Slide 9 — Live Demo

**[Live demonstration — 3 min]**

1. Upload 3 CSV files → Run Pipeline
2. Watch 13 agents execute in real time
3. Open Executive Report (HTML / DOCX / PDF)
4. Download Power BI `.pbip` project
5. Ask the Virtual CFO: *"Why did the current ratio decline?"*

Visual: Screenshot grid of the four main UI panels

---

## Slide 10 — Call to Action

**FinSight is open source (Apache 2.0)**

- Try it now: `docker compose up --build`
- Contribute: github.com/\<your-org\>/finsight
- Contact: \<your email / LinkedIn\>

*Built with IBM Bob · Python · Flask · Celery · Power BI · OpenAI / Gemini*

---

## Speaker Notes

- **Total time**: ≤ 3 minutes for demo + 5 minutes for slides = 8 min presentation
- Emphasize: **no LLM hallucination of numbers** (this is the key differentiator vs generic AI report tools)
- Emphasize: **Power BI zero-credential** — judges can try it themselves in 2 minutes
- End with: *"Every line of this platform was built in collaboration with IBM Bob"*
