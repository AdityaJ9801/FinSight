"""Report rendering with number binding (design doc §6.7): the report writer never types a
number, only {{m:metric_code:period_end}} placeholders. This module resolves them against
the `metrics` table (Indian digit grouping applied) and lints the draft for any raw digit
sequence that isn't a placeholder or a bare year -- the verifier treats a non-empty lint
result as an automatic fail.
"""
from __future__ import annotations

import base64
import io
import json
import re
from datetime import date, datetime, timezone
from typing import Any

from jinja2 import Template

from app.domain.taxonomy import interleave_charts_into_sections
from app.models.metric import Metric
from app.tools.registry import tool
from app.utils import storage

_PLACEHOLDER_RE = re.compile(r"\{\{m:([a-zA-Z0-9_.]+):([0-9\-]+)\}\}")
_RAW_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*\.?\d*(?![A-Za-z0-9])")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

_MONTH_NAMES = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?"
                 r"|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_DATE_RE = re.compile(
    rf"\b(?:{_MONTH_NAMES}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH_NAMES}\s+\d{{4}}"
    rf"|\d{{4}}-\d{{1,2}}-\d{{1,2}}"
    rf"|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{4}}"
    rf"|FY\s?\d{{2,4}}(?:[-/]\d{{2,4}})?)\b",
    re.IGNORECASE,
)


def format_indian_number(value: float, unit: str | None) -> str:
    if unit == "%":
        return f"{value * 100:.2f}%"
    if unit == "days":
        return f"{value:.0f} days"
    if unit == "x":
        return f"{value:.2f}x"

    negative = value < 0
    value = abs(value)
    int_part = int(round(value))
    s = str(int_part)
    if len(s) > 3:
        last3, rest = s[-3:], s[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        s = ",".join(groups) + "," + last3
    formatted = f"{'-' if negative else ''}{s}"
    return f"Rs. {formatted}" if unit in (None, "INR") else f"{formatted} {unit}"


def resolve_placeholders(text: str, dataset_version: str) -> tuple[str, list[str]]:
    unresolved: list[str] = []

    def repl(match: re.Match) -> str:
        code, period_str = match.group(1), match.group(2)
        try:
            period_end = date.fromisoformat(period_str)
        except ValueError:
            unresolved.append(match.group(0))
            return match.group(0)
        row = Metric.query.filter_by(dataset_version=dataset_version, metric_code=code, period_end=period_end).first()
        if row is None or row.value is None:
            unresolved.append(match.group(0))
            return match.group(0)
        return format_indian_number(float(row.value), row.unit)

    resolved = _PLACEHOLDER_RE.sub(repl, text)
    return resolved, unresolved


def lint_unbound_numbers(text: str) -> list[str]:
    """Runs on the DRAFT (placeholders still in {{m:...}} form) to catch any number the
    writer typed directly instead of via a placeholder."""
    stripped = _PLACEHOLDER_RE.sub("", text)
    stripped = _DATE_RE.sub("", stripped)
    issues = []
    for match in _RAW_NUMBER_RE.finditer(stripped):
        token = match.group(0)
        digits_only = token.replace(",", "").replace(".", "")
        if len(digits_only) < 2:
            continue
        if _YEAR_RE.match(token):
            continue
        issues.append(token)
    return issues


_HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<style>
  @page {
    size: A4 portrait;
    margin: 1.6cm 1.4cm;
  }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1e293b;
    background-color: #f8fafc;
    margin: 0;
    padding: 24px;
    line-height: 1.6;
    font-size: 14px;
  }
  .report-container {
    max-width: 900px;
    margin: 0 auto;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 36px 40px;
  }
  /* Header Banner */
  .header-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 24px;
    border-bottom: 2px solid #0f172a;
    padding-bottom: 16px;
  }
  .header-left {
    vertical-align: top;
    text-align: left;
  }
  .header-right {
    vertical-align: top;
    text-align: right;
  }
  .report-title {
    font-size: 26px;
    font-weight: 800;
    color: #0f172a;
    margin: 0 0 6px 0;
  }
  .report-subtitle {
    font-size: 13px;
    color: #64748b;
    margin: 0;
  }
  .status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
  }
  .badge-pass {
    background-color: #ecfdf5;
    color: #059669;
    border: 1px solid #a7f3d0;
  }
  .badge-unverified {
    background-color: #fffbeb;
    color: #b45309;
    border: 1px solid #fde68a;
  }
  /* KPI Dashboard Table */
  .kpi-section-title {
    font-size: 14px;
    font-weight: 700;
    text-transform: uppercase;
    color: #475569;
    letter-spacing: 0.05em;
    margin: 20px 0 10px 0;
  }
  .kpi-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 10px 0;
    margin-bottom: 28px;
  }
  .kpi-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 12px 14px;
    vertical-align: top;
    width: 20%;
  }
  .kpi-card-health {
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
  }
  .kpi-label {
    font-size: 11px;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    margin-bottom: 4px;
  }
  .kpi-value {
    font-size: 18px;
    font-weight: 800;
    color: #0f172a;
    margin-bottom: 2px;
  }
  .kpi-sub {
    font-size: 11px;
    color: #059669;
    font-weight: 600;
  }
  /* Section Blocks */
  .section-block {
    margin-bottom: 28px;
    padding-bottom: 20px;
    border-bottom: 1px solid #f1f5f9;
  }
  .section-block:last-child {
    border-bottom: none;
  }
  .section-heading {
    font-size: 17px;
    font-weight: 700;
    color: #1e3a8a;
    margin: 0 0 10px 0;
    padding-left: 10px;
    border-left: 4px solid #2563eb;
  }
  .section-body {
    font-size: 13.5px;
    color: #334155;
    line-height: 1.7;
    margin: 0 0 14px 0;
    white-space: pre-wrap;
  }
  .data-quality-block {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 14px 16px;
    margin-top: 20px;
  }
  .data-quality-heading {
    font-size: 14px;
    font-weight: 700;
    color: #334155;
    margin: 0 0 6px 0;
  }
  /* Data Diagnostic Styles */
  .data-diagnostic-container {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 22px 24px;
    margin-top: 28px;
    margin-bottom: 24px;
    page-break-inside: avoid;
  }
  .diagnostic-header {
    border-bottom: 2px solid #0284c7;
    padding-bottom: 10px;
    margin-bottom: 16px;
  }
  .diagnostic-badge {
    display: inline-block;
    background: #e0f2fe;
    color: #0369a1;
    border: 1px solid #bae6fd;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 4px;
    margin-bottom: 6px;
    letter-spacing: 0.05em;
  }
  .diagnostic-heading {
    font-size: 18px;
    font-weight: 800;
    color: #0f172a;
    margin: 0;
  }
  .diagnostic-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
    margin-bottom: 16px;
    font-size: 12.5px;
  }
  .diagnostic-table th {
    background: #f1f5f9;
    color: #334155;
    font-weight: 700;
    text-align: left;
    padding: 8px 10px;
    border: 1px solid #e2e8f0;
  }
  .diagnostic-table td {
    padding: 8px 10px;
    border: 1px solid #e2e8f0;
    color: #334155;
    vertical-align: top;
  }
  .diag-pill {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
  }
  .diag-pill-pass { background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
  .diag-pill-warn { background: #fef9c3; color: #854d0e; border: 1px solid #fef08a; }
  .diag-pill-fail { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }

  .metric-diagnostic-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #0284c7;
    border-radius: 6px;
    padding: 14px 16px;
    margin-bottom: 14px;
    page-break-inside: avoid;
  }
  .mdiag-title-row {
    margin-bottom: 8px;
  }
  .mdiag-title {
    font-size: 14px;
    font-weight: 700;
    color: #0f172a;
    display: inline-block;
    margin-right: 8px;
  }
  .mdiag-badge {
    display: inline-block;
    background: #e2e8f0;
    color: #334155;
    border: 1px solid #cbd5e1;
    font-size: 10.5px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 3px;
  }
  .mdiag-formula {
    font-size: 11px;
    color: #0369a1;
    background: #f0f9ff;
    padding: 4px 8px;
    border-radius: 4px;
    margin-top: 5px;
    font-family: monospace;
    display: inline-block;
  }
  .mdiag-step-title {
    font-size: 12px;
    font-weight: 700;
    color: #1e293b;
    margin-top: 8px;
    margin-bottom: 3px;
  }
  .mdiag-text {
    font-size: 12.5px;
    color: #475569;
    line-height: 1.5;
    margin: 0;
  }
  .mdiag-bullets {
    margin: 3px 0 8px 18px;
    padding: 0;
    font-size: 12px;
    color: #475569;
    line-height: 1.55;
  }
  /* Interleaved Charts */
  .chart-container {
    margin: 14px 0 18px 0;
    text-align: center;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 14px;
    page-break-inside: avoid;
  }
  .chart-title {
    font-size: 13px;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 8px 0;
    text-align: left;
  }
  .chart-image {
    max-width: 580px;
    width: 100%;
    height: auto;
    border-radius: 4px;
    display: block;
    margin: 0 auto;
  }
  .chart-caption {
    font-size: 12px;
    color: #64748b;
    font-style: italic;
    margin: 8px 0 0 0;
    text-align: left;
    background: #f8fafc;
    padding: 6px 10px;
    border-radius: 4px;
    border-left: 3px solid #94a3b8;
  }
  .warning-block {
    background-color: #fffbeb;
    border: 1px solid #fde68a;
    border-left: 4px solid #f59e0b;
    border-radius: 4px;
    padding: 12px 16px;
    margin-bottom: 20px;
  }
  .warning-heading {
    font-size: 14px;
    font-weight: 700;
    color: #b45309;
    margin: 0 0 4px 0;
  }
  .warning-body {
    font-size: 12.5px;
    color: #78350f;
    margin: 0;
  }
</style>
</head>
<body>
<div class="report-container">

  <!-- Header Banner -->
  <table class="header-table">
    <tr>
      <td class="header-left">
        <h1 class="report-title">{{ title }}</h1>
        <p class="report-subtitle">Generated on {{ generated_date }} | Entity Financial Analysis</p>
      </td>
      <td class="header-right">
        {% if is_verified %}
          <span class="status-badge badge-pass">✓ Verified Report</span>
        {% else %}
          <span class="status-badge badge-unverified">⚠ Draft / Unverified</span>
        {% endif %}
      </td>
    </tr>
  </table>

  <!-- KPI Executive Dashboard -->
  {% if kpi_cards or health_score %}
  <div class="kpi-section-title">Executive Performance Overview</div>
  <table class="kpi-table">
    <tr>
      {% if health_score %}
      <td class="kpi-card kpi-card-health">
        <div class="kpi-label">Health Score</div>
        <div class="kpi-value">{{ health_score.score }}<span style="font-size: 12px; font-weight: normal; color: #64748b;">/100</span></div>
        <div class="kpi-sub">Rating: {{ health_score.rating }}</div>
      </td>
      {% endif %}
      {% for kpi in kpi_cards %}
      <td class="kpi-card">
        <div class="kpi-label">{{ kpi.label }}</div>
        <div class="kpi-value">{{ kpi.value }}</div>
        {% if kpi.sub %}<div class="kpi-sub">{{ kpi.sub }}</div>{% endif %}
      </td>
      {% endfor %}
    </tr>
  </table>
  {% endif %}

  <!-- Report Sections with Interleaved Charts -->
  {% for section in sections %}
    {% if "Not Verified" in section.heading %}
      <div class="warning-block">
        <div class="warning-heading">{{ section.heading }}</div>
        <p class="warning-body">{{ section.body }}</p>
      </div>
    {% elif section.kind == "data_diagnostic" or "Data Diagnostic" in section.heading %}
      <div class="data-diagnostic-container">
        <div class="diagnostic-header">
          <span class="diagnostic-badge">🔬 Virtual CFO Data Diagnostic</span>
          <h2 class="diagnostic-heading">{{ section.heading }}</h2>
        </div>

        {% if section.integrity_summary %}
        <div style="margin-bottom: 16px;">
          <div style="font-size: 13px; font-weight: 700; color: #1e293b; margin-bottom: 6px;">1. Dataset Ingestion & Ledger Integrity Audit</div>
          <table class="diagnostic-table">
            <tr>
              <th style="width: 25%;">Financial Facts</th>
              <td style="width: 25%;">{{ section.integrity_summary.facts_count }} line items</td>
              <th style="width: 25%;">Reconciliation Status</th>
              <td style="width: 25%;">
                <span class="diag-pill diag-pill-{{ section.integrity_summary.recon_badge_class }}">
                  {{ section.integrity_summary.reconciliation_status }}
                </span>
              </td>
            </tr>
            <tr>
              <th>Reporting Periods</th>
              <td>{{ section.integrity_summary.periods_str }}</td>
              <th>Mapping Confidence</th>
              <td>{{ section.integrity_summary.mapping_confidence_pct }}%</td>
            </tr>
            {% if section.integrity_summary.statements_covered %}
            <tr>
              <th>Statements Covered</th>
              <td colspan="3">{{ section.integrity_summary.statements_covered|join(", ") }}</td>
            </tr>
            {% endif %}
          </table>

          {% if section.integrity_summary.checks %}
          <div style="font-size: 12px; font-weight: 700; color: #475569; margin: 8px 0 4px 0;">Statement Reconciliation Checks:</div>
          <table class="diagnostic-table">
            <tr>
              <th>Reconciliation Check</th>
              <th style="width: 15%; text-align: center;">Status</th>
              <th style="width: 25%; text-align: right;">Variance / Delta</th>
            </tr>
            {% for chk in section.integrity_summary.checks %}
            <tr>
              <td>{{ chk.label }}</td>
              <td style="text-align: center;">
                <span class="diag-pill diag-pill-{{ chk.status }}">{{ chk.status_text }}</span>
              </td>
              <td style="text-align: right;">
                {% if chk.diff == 0 %}
                  <span style="color: #15803d; font-weight: 600;">₹0.00 (Exact Match)</span>
                {% else %}
                  <span style="color: #b91c1c;">₹{{ "%.2f"|format(chk.diff) }}</span>
                {% endif %}
              </td>
            </tr>
            {% endfor %}
          </table>
          {% endif %}
        </div>
        {% endif %}

        {% if section.metric_diagnostics %}
        <div>
          <div style="font-size: 13px; font-weight: 700; color: #1e293b; margin-bottom: 6px;">2. Virtual CFO Root-Cause Metric Diagnostics (Flowchart Compendium)</div>
          <p style="font-size: 12px; color: #64748b; margin-top: 0; margin-bottom: 12px;">
            Automated 6-level reverse-flow drill-down answering <em>What changed? Why did it change? What caused it? What to investigate? What to ask management?</em>
          </p>

          {% for mdiag in section.metric_diagnostics %}
          <div class="metric-diagnostic-card">
            <div class="mdiag-title-row">
              <span class="mdiag-title">{{ mdiag.canonical_name }}</span>
              <span class="mdiag-badge">{{ mdiag.direction_badge }}</span>
              <div><span class="mdiag-formula">Formula: {{ mdiag.formula }}</span></div>
            </div>
            
            <div class="mdiag-step-title">1. What Changed:</div>
            <p class="mdiag-text">{{ mdiag.what_changed }}</p>

            <div class="mdiag-step-title">2. Why Did It Change (Governing Components):</div>
            <ul class="mdiag-bullets">
              {% for comp in mdiag.why_did_it_change %}
                <li><strong>{{ comp }}</strong></li>
              {% endfor %}
            </ul>

            <div class="mdiag-step-title">3. Operational Root Causes:</div>
            <ul class="mdiag-bullets">
              {% for rc in mdiag.root_causes %}
                <li><strong>{{ rc.name }}</strong> (<em>{{ rc.component }}</em>): {{ rc.root_cause }}</li>
              {% endfor %}
            </ul>

            <div class="mdiag-step-title">4. Operational Audit Checklist (What to Investigate):</div>
            <ul class="mdiag-bullets">
              {% for inv in mdiag.investigations %}
                <li>☐ {{ inv }}</li>
              {% endfor %}
            </ul>

            <div class="mdiag-step-title">5. High-Impact Questions for Management:</div>
            <ul class="mdiag-bullets">
              {% for q in mdiag.questions %}
                <li>❓ {{ q }}</li>
              {% endfor %}
            </ul>
          </div>
          {% endfor %}
        </div>
        {% endif %}

        {% if section.integrity_summary and section.integrity_summary.notes %}
        <div style="margin-top: 14px; padding: 10px 14px; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 4px;">
          <div style="font-size: 12px; font-weight: 700; color: #334155; margin-bottom: 4px;">3. Data Quality & Methodology Notes</div>
          <p style="margin: 0; font-size: 12px; color: #475569; line-height: 1.5;">{{ section.integrity_summary.notes }}</p>
        </div>
        {% endif %}
      </div>
    {% elif section.kind == "data_quality" or "Data Quality" in section.heading %}
      <div class="data-quality-block">
        <div class="data-quality-heading">{{ section.heading }}</div>
        <p style="margin: 0; font-size: 12.5px; color: #475569;">{{ section.body }}</p>
      </div>
    {% else %}
      <div class="section-block">
        <h2 class="section-heading">{{ section.heading }}</h2>
        <div class="section-body">{{ section.body }}</div>

        {% if section.charts %}
          {% for chart in section.charts %}
          <div class="chart-container">
            <div class="chart-title">Figure: {{ chart.title }}</div>
            <img class="chart-image" src="{{ chart.png_base64 }}" alt="{{ chart.title }}">
            {% if chart.caption %}
            <div class="chart-caption">{{ chart.caption }}</div>
            {% endif %}
          </div>
          {% endfor %}
        {% endif %}
      </div>
    {% endif %}
  {% endfor %}

  <!-- Unassigned Charts (if any) -->
  {% if unassigned_charts %}
  <div class="section-block" style="margin-top: 24px;">
    <h2 class="section-heading">Additional Visualizations</h2>
    {% for chart in unassigned_charts %}
    <div class="chart-container">
      <div class="chart-title">Figure: {{ chart.title }}</div>
      <img class="chart-image" src="{{ chart.png_base64 }}" alt="{{ chart.title }}">
      {% if chart.caption %}
      <div class="chart-caption">{{ chart.caption }}</div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}

</div>
</body>
</html>
""")


def _extract_kpis(job_id: str, metadata: dict | None = None) -> tuple[dict | None, list[dict]]:
    health_score = None
    kpi_cards: list[dict] = []

    if metadata and metadata.get("health_score"):
        health_score = metadata["health_score"]
    if metadata and metadata.get("kpis"):
        return health_score, metadata["kpis"]

    insights_path = f"{job_id}/delivery/insights.json"
    if storage.resolve(insights_path).exists():
        try:
            payload = json.loads(storage.resolve(insights_path).read_text())
            health_score = health_score or payload.get("health_score")
            metrics = payload.get("metrics", [])
            latest_by_code: dict[str, dict] = {}
            for m in metrics:
                code = m.get("metric_code") or m.get("code")
                if code and m.get("value") is not None:
                    if code not in latest_by_code or m.get("period_end", "") > latest_by_code[code].get("period_end", ""):
                        latest_by_code[code] = m

            target_kpis = [
                ("gross_profit_pct", "Gross Margin", "%"),
                ("ebitda_margin", "EBITDA Margin", "%"),
                ("net_profit_margin", "Net Margin", "%"),
                ("current_ratio", "Current Ratio", "x"),
                ("debt_to_equity", "Debt / Equity", "x"),
                ("cash_conversion_cycle", "Cash Cycle", "days"),
            ]
            for code, label, _ in target_kpis:
                if code in latest_by_code:
                    item = latest_by_code[code]
                    val_str = format_indian_number(float(item["value"]), item.get("unit"))
                    kpi_cards.append({
                        "label": label,
                        "value": val_str,
                        "sub": item.get("period_end", ""),
                    })
                if len(kpi_cards) >= 4:
                    break
        except Exception:
            pass

    return health_score, kpi_cards


def render_html(
    job_id: str,
    title: str,
    sections: list[dict],
    charts: list[dict] | None = None,
    metadata: dict | None = None,
) -> dict:
    charts = charts or []
    has_diagnostic = any(s.get("kind") == "data_diagnostic" or "Data Diagnostic" in s.get("heading", "") for s in sections)
    if not has_diagnostic:
        draft_path = f"{job_id}/delivery/draft.json"
        if storage.resolve(draft_path).exists():
            try:
                draft_data = json.loads(storage.resolve(draft_path).read_text())
                if draft_data.get("data_diagnostic_section"):
                    sections = list(sections) + [draft_data["data_diagnostic_section"]]
            except Exception:
                pass
    enriched_sections, unassigned = interleave_charts_into_sections(sections, charts)
    health_score, kpi_cards = _extract_kpis(job_id, metadata)
    is_verified = not any("Not Verified" in s.get("heading", "") for s in sections)
    generated_date = datetime.now(timezone.utc).strftime("%d %b %Y")

    html = _HTML_TEMPLATE.render(
        title=title,
        sections=enriched_sections,
        unassigned_charts=unassigned,
        health_score=health_score,
        kpi_cards=kpi_cards,
        is_verified=is_verified,
        generated_date=generated_date,
    )
    uri = storage.write_text(f"{job_id}/report/report.html", html)
    return {"html_uri": uri, "html": html}


def render_docx(
    job_id: str,
    title: str,
    sections: list[dict],
    charts: list[dict] | None = None,
) -> str:
    from docx import Document as DocxDocument
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT

    charts = charts or []
    has_diagnostic = any(s.get("kind") == "data_diagnostic" or "Data Diagnostic" in s.get("heading", "") for s in sections)
    if not has_diagnostic:
        draft_path = f"{job_id}/delivery/draft.json"
        if storage.resolve(draft_path).exists():
            try:
                draft_data = json.loads(storage.resolve(draft_path).read_text())
                if draft_data.get("data_diagnostic_section"):
                    sections = list(sections) + [draft_data["data_diagnostic_section"]]
            except Exception:
                pass
    enriched_sections, unassigned = interleave_charts_into_sections(sections, charts)
    health_score, kpi_cards = _extract_kpis(job_id)

    doc = DocxDocument()

    # Document Header
    title_p = doc.add_paragraph()
    title_run = title_p.add_run(title)
    title_run.font.size = Pt(22)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(15, 23, 42)

    subtitle_p = doc.add_paragraph()
    sub_run = subtitle_p.add_run(f"Generated {datetime.now(timezone.utc).strftime('%B %d, %Y')} | FinSight Executive Analysis")
    sub_run.font.size = Pt(10)
    sub_run.font.italic = True
    sub_run.font.color.rgb = RGBColor(100, 116, 139)

    # Executive KPI Table
    if kpi_cards or health_score:
        doc.add_heading("Executive KPI Summary", level=2)
        items = []
        if health_score:
            items.append(("Financial Health Score", f"{health_score['score']} / 100", f"Rating: {health_score['rating']}"))
        for k in kpi_cards:
            items.append((k["label"], k["value"], k.get("sub", "")))

        table = doc.add_table(rows=len(items) + 1, cols=3)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = "Indicator"
        hdr_cells[1].text = "Value"
        hdr_cells[2].text = "Period / Context"
        for i, (ind, val, ctx) in enumerate(items):
            row_cells = table.rows[i + 1].cells
            row_cells[0].text = ind
            row_cells[1].text = val
            row_cells[2].text = ctx
        doc.add_paragraph()

    # Sections with Interleaved Charts
    for section in enriched_sections:
        if section.get("kind") == "data_diagnostic" or "Data Diagnostic" in section.get("heading", ""):
            doc.add_heading(section["heading"], level=2)
            int_sum = section.get("integrity_summary")
            if int_sum:
                doc.add_heading("1. Dataset Ingestion & Ledger Integrity Audit", level=3)
                p = doc.add_paragraph()
                p.add_run(f"Financial Facts Ingested: {int_sum.get('facts_count')} line items across {', '.join(int_sum.get('statements_covered', []))}\n")
                p.add_run(f"Reporting Periods: {int_sum.get('periods_str')}\n")
                p.add_run(f"Reconciliation Status: {int_sum.get('reconciliation_status')}\n")
                p.add_run(f"CoA Mapping Confidence: {int_sum.get('mapping_confidence_pct')}%\n")
                if int_sum.get("checks"):
                    chk_table = doc.add_table(rows=len(int_sum["checks"]) + 1, cols=3)
                    chk_table.alignment = WD_TABLE_ALIGNMENT.CENTER
                    h_cells = chk_table.rows[0].cells
                    h_cells[0].text = "Reconciliation Check"
                    h_cells[1].text = "Status"
                    h_cells[2].text = "Variance"
                    for idx, chk in enumerate(int_sum["checks"]):
                        r_cells = chk_table.rows[idx + 1].cells
                        r_cells[0].text = chk["label"]
                        r_cells[1].text = chk["status_text"]
                        r_cells[2].text = f"Rs.{chk['diff']:,.2f}" if chk["diff"] != 0 else "Exact Match"
                    doc.add_paragraph()

            mdiags = section.get("metric_diagnostics")
            if mdiags:
                doc.add_heading("2. Virtual CFO Root-Cause Metric Diagnostics", level=3)
                for mdiag in mdiags:
                    doc.add_heading(f"{mdiag['canonical_name']} ({mdiag['direction_badge']})", level=4)
                    fp = doc.add_paragraph()
                    f_run = fp.add_run(f"Formula: {mdiag['formula']}")
                    f_run.font.italic = True
                    f_run.font.size = Pt(9.5)
                    doc.add_paragraph(f"1. What Changed: {mdiag['what_changed']}")
                    doc.add_paragraph("2. Governing Components: " + ", ".join(mdiag["why_did_it_change"]))
                    doc.add_paragraph("3. Operational Root Causes:")
                    for rc in mdiag["root_causes"]:
                        doc.add_paragraph(f"* {rc['name']} ({rc['component']}): {rc['root_cause']}")
                    doc.add_paragraph("4. Operational Audit Checklist (What to Investigate):")
                    for inv in mdiag["investigations"]:
                        doc.add_paragraph(f"* [ ] {inv}")
                    doc.add_paragraph("5. Questions for Management:")
                    for q in mdiag["questions"]:
                        doc.add_paragraph(f"* {q}")
                    doc.add_paragraph()

            if int_sum and int_sum.get("notes"):
                doc.add_heading("3. Data Quality & Methodology Notes", level=3)
                doc.add_paragraph(int_sum["notes"])
            continue

        doc.add_heading(section["heading"], level=2)
        doc.add_paragraph(section["body"])

        if section.get("charts"):
            for chart in section["charts"]:
                doc.add_heading(chart["title"], level=3)
                png_uri = chart.get("png_uri")
                png_bytes = None
                if png_uri:
                    try:
                        png_bytes = storage.resolve(png_uri).read_bytes()
                    except Exception:
                        pass
                if not png_bytes and chart.get("png_base64"):
                    try:
                        raw_b64 = chart["png_base64"].split(",", 1)[-1]
                        png_bytes = base64.b64decode(raw_b64)
                    except Exception:
                        pass
                if png_bytes:
                    doc.add_picture(io.BytesIO(png_bytes), width=Inches(5.5))
                if chart.get("caption"):
                    cap_p = doc.add_paragraph(chart["caption"])
                    cap_p.runs[0].font.italic = True
                    cap_p.runs[0].font.size = Pt(9.5)

    if unassigned:
        doc.add_heading("Additional Visualizations", level=2)
        for chart in unassigned:
            doc.add_heading(chart["title"], level=3)
            png_uri = chart.get("png_uri")
            png_bytes = None
            if png_uri:
                try:
                    png_bytes = storage.resolve(png_uri).read_bytes()
                except Exception:
                    pass
            if not png_bytes and chart.get("png_base64"):
                try:
                    raw_b64 = chart["png_base64"].split(",", 1)[-1]
                    png_bytes = base64.b64decode(raw_b64)
                except Exception:
                    pass
            if png_bytes:
                doc.add_picture(io.BytesIO(png_bytes), width=Inches(5.5))
            if chart.get("caption"):
                doc.add_paragraph(chart["caption"])

    buf = io.BytesIO()
    doc.save(buf)
    return storage.write_bytes(f"{job_id}/report/report.docx", buf.getvalue())


def render_pdf(job_id: str, html: str) -> str:
    from xhtml2pdf import pisa

    buf = io.BytesIO()
    pisa.CreatePDF(src=html, dest=buf)
    return storage.write_bytes(f"{job_id}/report/report.pdf", buf.getvalue())


tool("report.render", allowed_agents=["report_writer"])(render_html)
