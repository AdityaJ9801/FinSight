"""Dynamic Chart Generator for User-Requested Visualizations.

Enables the Ask Chatbot (and API) to dynamically synthesize and render new charts on-the-fly
from ANY dataset attribute, measure, or canonical metric based on the user's natural language prompt.
"""
from __future__ import annotations

import re
from typing import Any

from app.orchestrator import blackboard
from app.tools.chart_render import render_chart
from app.utils.ids import new_id


def generate_chart_for_prompt(job_id: str, question: str) -> dict[str, Any] | None:
    """Inspects the job's structured datasets and precomputed metrics, infers the requested
    dimension and measure from the user's question, generates a new chart, persists it to
    the job's blackboard collection, and returns the rendered chart object.
    """
    datasets = blackboard.read(job_id, "structured_datasets") or []
    ds_profile = blackboard.read(job_id, "dataset_profile") or {}
    q_low = question.lower()

    # Desired chart type
    chart_type = "bar"
    if any(w in q_low for w in ("horizontal", "hbar", "ranking", "top")):
        chart_type = "hbar"
    elif any(w in q_low for w in ("line", "trend", "over time", "progression", "growth")):
        chart_type = "line"
    elif any(w in q_low for w in ("donut", "pie", "share", "split")):
        chart_type = "bar"

    matched_chart: dict[str, Any] | None = None

    # 1. Match against structured dataset attributes and measures
    for ds in datasets:
        records = ds.get("records", [])
        aggregations = ds.get("aggregations", {})
        dimensions = ds.get("dimensions", [])
        measures = ds.get("measures", [])

        # Find best matching dimension
        target_dim = None
        for dim in dimensions:
            dim_words = [w for w in re.split(r"[_\s]+", dim.lower()) if len(w) > 2]
            if dim.lower() in q_low or any(w in q_low for w in dim_words):
                target_dim = dim
                break
        if not target_dim and dimensions:
            # Fallback hints
            if any(w in q_low for w in ("country", "nation", "geography")):
                target_dim = next((d for d in dimensions if "country" in d.lower()), None)
            elif any(w in q_low for w in ("segment", "sector", "tier")):
                target_dim = next((d for d in dimensions if "segment" in d.lower()), None)
            elif any(w in q_low for w in ("product", "item", "sku")):
                target_dim = next((d for d in dimensions if "product" in d.lower()), None)
            elif any(w in q_low for w in ("party", "client", "customer", "vendor")):
                target_dim = next((d for d in dimensions if "particulars" in d.lower() or "party" in d.lower()), None)

        if not target_dim and dimensions:
            target_dim = dimensions[0]

        # Find best matching measure
        target_measure = None
        for m in measures:
            m_words = [w for w in re.split(r"[_\s]+", m.lower()) if len(w) > 2]
            if m.lower() in q_low or any(w in q_low for w in m_words):
                target_measure = m
                break
        if not target_measure and measures:
            if any(w in q_low for w in ("profit", "margin", "income")):
                target_measure = next((m for m in measures if "profit" in m.lower()), None)
            elif any(w in q_low for w in ("sale", "revenue", "turnover")):
                target_measure = next((m for m in measures if "sale" in m.lower()), None)
            elif any(w in q_low for w in ("unit", "volume", "quantity", "qty")):
                target_measure = next((m for m in measures if "unit" in m.lower()), None)
            elif any(w in q_low for w in ("debit", "withdrawal", "spent")):
                target_measure = next((m for m in measures if "debit" in m.lower()), None)
            elif any(w in q_low for w in ("credit", "deposit", "receipt")):
                target_measure = next((m for m in measures if "credit" in m.lower()), None)

        if not target_measure and measures:
            target_measure = measures[0]

        if target_dim and target_measure:
            # Group records or use precomputed aggregations
            agg_map = aggregations.get(target_dim)
            if not agg_map and records:
                agg_map = {}
                for r in records:
                    val = str(r.get(target_dim, "")).strip()
                    if not val:
                        continue
                    agg_map.setdefault(val, {})
                    agg_map[val][target_measure] = agg_map[val].get(target_measure, 0.0) + float(r.get(target_measure, 0.0) or 0.0)

            if agg_map:
                sorted_items = sorted(
                    agg_map.items(),
                    key=lambda it: float(it[1].get(target_measure, 0.0) or 0.0),
                    reverse=True,
                )[:12]

                labels = [str(it[0]) for it in sorted_items]
                values = [round(float(it[1].get(target_measure, 0.0) or 0.0), 2) for it in sorted_items]

                title = f"{target_measure} by {target_dim}"
                unit = "INR" if any(w in target_measure.lower() for w in ("amount", "sales", "price", "profit", "cogs", "debit", "credit")) else None
                takeaway = f"Top {len(labels)} {target_dim.lower()}s ordered by {target_measure}."

                if len(labels) > 6 or any(len(str(l)) > 15 for l in labels):
                    chart_type = "hbar"

                chart_id = new_id("chart_dyn_")
                try:
                    rendered = render_chart(
                        job_id=job_id,
                        chart_id=chart_id,
                        title=title,
                        chart_type=chart_type,
                        labels=labels,
                        series={target_measure: values},
                        unit=unit,
                        subtitle=takeaway,
                    )
                    matched_chart = {
                        "chart_id": chart_id,
                        "title": title,
                        "caption": f"Custom chart generated for query: '{question}'",
                        "takeaway": takeaway,
                        "section_key": "chat_custom",
                        "is_custom": True,
                        **rendered,
                    }
                    break
                except Exception:
                    continue

    # 2. If no structured dataset matched, check candidate charts from dataset_profile
    if not matched_chart and ds_profile.get("dynamic_chart_candidates"):
        candidates = ds_profile["dynamic_chart_candidates"]
        cand = next(
            (c for c in candidates if any(w in c["title"].lower() for w in q_low.split() if len(w) > 3)),
            candidates[0],
        )
        chart_id = new_id("chart_dyn_")
        try:
            rendered = render_chart(
                job_id=job_id,
                chart_id=chart_id,
                title=cand["title"],
                chart_type=cand["chart_type"],
                labels=cand["labels"],
                series=cand["series"],
                unit=cand.get("unit"),
                subtitle=cand.get("takeaway"),
            )
            matched_chart = {
                "chart_id": chart_id,
                "title": cand["title"],
                "caption": f"Custom chart generated for query: '{question}'",
                "takeaway": cand.get("takeaway", ""),
                "section_key": "chat_custom",
                "is_custom": True,
                **rendered,
            }
        except Exception:
            pass

    # Save to blackboard so it persists in the Charts tab
    if matched_chart:
        all_charts = blackboard.read(job_id, "charts") or []
        # Check if already present
        if not any(c.get("title") == matched_chart["title"] for c in all_charts):
            all_charts.append(matched_chart)
            blackboard.write(job_id, "charts", all_charts)

    return matched_chart
