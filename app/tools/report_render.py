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
