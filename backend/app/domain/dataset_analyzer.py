"""Dataset-First Financial Intelligence & Attribute Analyzer.

Universal analysis engine that inspects ANY uploaded financial dataset (regardless of whether
it conforms to standard Chart-of-Accounts financial statements) before predefined calculations:
- Detects dataset archetypes (transactional register, dimensional matrix, schedule breakdown)
- Profiles attributes, dimensions, and measures
- Computes Pareto / 80-20 concentrations, margin spreads, top drivers
- Formulates high-priority data-driven findings
- Prepares dynamic chart specifications based on actual dataset attributes
"""
from __future__ import annotations

import re
from typing import Any

from app.orchestrator import blackboard


def analyze_dataset_profile(job_id: str, datasets: list[dict] | None = None) -> dict[str, Any]:
    """Analyzes all structured datasets available on the blackboard for this job.
    Returns a unified profile with archetypes, metrics summary, dimensional breakdowns,
    key findings, and dynamic chart candidates.
    """
    if datasets is None:
        datasets = blackboard.read(job_id, "structured_datasets") or []

    profile: dict[str, Any] = {
        "job_id": job_id,
        "datasets_count": len(datasets),
        "datasets": [],
        "findings": [],
        "dynamic_chart_candidates": [],
    }

    if not datasets:
        return profile

    all_findings = []
    chart_candidates = []

    for ds in datasets:
        name = ds.get("name", "Dataset")
        dimensions = ds.get("dimensions", [])
        measures = ds.get("measures", [])
        records = ds.get("records", [])
        aggregations = ds.get("aggregations", {})
        row_count = ds.get("row_count", len(records))

        ds_summary: dict[str, Any] = {
            "name": name,
            "filename": ds.get("filename", ""),
            "dimensions": dimensions,
            "measures": measures,
            "row_count": row_count,
            "measure_totals": {},
            "top_drivers": {},
        }

        # 1. Measure Totals
        for m in measures:
            vals = [float(r.get(m, 0.0) or 0.0) for r in records if m in r]
            if vals:
                tot = sum(vals)
                avg = tot / len(vals)
                ds_summary["measure_totals"][m] = {
                    "sum": round(tot, 2),
                    "avg": round(avg, 2),
                    "max": round(max(vals), 2),
                    "min": round(min(vals), 2),
                }

        # Primary measure of interest (Sales, Gross Total, Debit Amount, Profit, Amount)
        primary_measure = None
        for cand in ("Sales", "Gross Total", "Debit Amount", "Gross Sales", "Amount", "Value", "Profit"):
            match = next((m for m in measures if cand.lower() in m.lower()), None)
            if match:
                primary_measure = match
                break
        if not primary_measure and measures:
            primary_measure = measures[0]

        profit_measure = next((m for m in measures if "profit" in m.lower() or "margin" in m.lower()), None)

        # 2. Dimensional Drivers & 80/20 Concentration
        for dim, agg in aggregations.items():
            if not primary_measure:
                continue
            # Rank values by primary measure
            sorted_items = sorted(
                agg.items(),
                key=lambda it: float(it[1].get(primary_measure, 0.0) or 0.0),
                reverse=True,
            )
            total_prim = ds_summary["measure_totals"].get(primary_measure, {}).get("sum", 0.0)

            if total_prim > 0 and sorted_items:
                top_3 = sorted_items[:3]
                top_3_sum = sum(float(it[1].get(primary_measure, 0.0) or 0.0) for it in top_3)
                share_pct = (top_3_sum / total_prim) * 100

                top_names = [it[0] for it in top_3]
                ds_summary["top_drivers"][dim] = {
                    "top_names": top_names,
                    "share_pct": round(share_pct, 1),
                    "items_count": len(sorted_items),
                }

                if share_pct >= 40.0 and len(sorted_items) >= 3:
                    all_findings.append({
                        "module": "dataset_analysis",
                        "severity": "info" if share_pct < 75 else "warn",
                        "title": f"High Concentration in {dim} ({round(share_pct, 1)}%)",
                        "body": (
                            f"In dataset '{name}', the top {min(3, len(top_names))} {dim.lower()}s "
                            f"({', '.join(top_names)}) account for {round(share_pct, 1)}% of total "
                            f"{primary_measure} ({round(top_3_sum, 2):,})."
                        ),
                    })

            # Check Margin Spread if profit measure is present
            if profit_measure and primary_measure and profit_measure != primary_measure:
                margins = []
                for val_name, m_dict in sorted_items[:8]:
                    rev = float(m_dict.get(primary_measure, 0.0) or 0.0)
                    prof = float(m_dict.get(profit_measure, 0.0) or 0.0)
                    if rev > 0:
                        margin_pct = (prof / rev) * 100
                        margins.append((val_name, margin_pct, prof))

                if margins:
                    best_seg = max(margins, key=lambda x: x[1])
                    worst_seg = min(margins, key=lambda x: x[1])
                    if best_seg[0] != worst_seg[0] and (best_seg[1] - worst_seg[1] >= 10.0 or worst_seg[1] < 0):
                        all_findings.append({
                            "module": "dataset_analysis",
                            "severity": "warn" if worst_seg[1] < 0 else "info",
                            "title": f"{dim} Profitability Divergence",
                            "body": (
                                f"Profit margin across {dim} varies significantly: '{best_seg[0]}' leads with "
                                f"{best_seg[1]:.1f}% margin, while '{worst_seg[0]}' generates "
                                f"{worst_seg[1]:.1f}% margin ({'net loss' if worst_seg[1] < 0 else 'lower yield'})."
                            ),
                        })

            # Generate dynamic chart candidates for high-quality dimensions
            if sorted_items and len(sorted_items) >= 2:
                top_slice = sorted_items[:10]
                labels = [it[0] for it in top_slice]

                # Single or dual series chart
                series = {}
                series[primary_measure] = [round(float(it[1].get(primary_measure, 0.0) or 0.0), 2) for it in top_slice]
                if profit_measure and profit_measure in measures and profit_measure != primary_measure:
                    series[profit_measure] = [round(float(it[1].get(profit_measure, 0.0) or 0.0), 2) for it in top_slice]

                chart_type = "hbar" if len(labels) > 5 or any(len(str(l)) > 15 for l in labels) else "bar"
                title = f"{primary_measure} by {dim}"
                if profit_measure and profit_measure in series:
                    title = f"{primary_measure} and {profit_measure} by {dim}"

                chart_candidates.append({
                    "title": title,
                    "section_key": "dataset_attributes",
                    "chart_type": chart_type,
                    "labels": [str(l)[:30] for l in labels],
                    "series": series,
                    "unit": "INR" if any("amount" in m.lower() or "price" in m.lower() or "sales" in m.lower() for m in series) else None,
                    "takeaway": f"Distribution across top {len(labels)} {dim.lower()}s in {name}.",
                    "dimension": dim,
                    "dataset_name": name,
                })

        profile["datasets"].append(ds_summary)

    profile["findings"] = all_findings
    profile["dynamic_chart_candidates"] = chart_candidates

    # Write profile to blackboard for downstream agents
    blackboard.write(job_id, "dataset_profile", profile)
    return profile
