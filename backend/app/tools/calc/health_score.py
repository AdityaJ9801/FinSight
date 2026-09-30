"""Financial health score: a transparent, rules-table score over metric bands (design doc
§6.6: "a rules table, not an LLM"). The LLM (insight reasoner) explains the drivers; it
never produces the score itself.
"""
from __future__ import annotations

from app.tools.registry import tool

# Each band: (threshold, points). Evaluated top-down; first threshold the value clears wins.
# lower_is_better=True means the metric is scored against thresholds in descending order.
_BANDS = {
    "current_ratio": (20, False, [(2.0, 20), (1.5, 15), (1.0, 10), (0.75, 5)]),
    "debt_to_equity": (20, True, [(0.5, 20), (1.0, 15), (2.0, 10), (3.0, 5)]),
    "net_profit_margin": (20, False, [(0.15, 20), (0.08, 15), (0.03, 10), (0.0, 5)]),
    "interest_coverage": (20, False, [(5.0, 20), (3.0, 15), (1.5, 10), (1.0, 5)]),
    "dso": (20, True, [(30, 20), (60, 15), (90, 10), (120, 5)]),
}


def _score_metric(code: str, value: float) -> int:
    _, lower_is_better, bands = _BANDS[code]
    if lower_is_better:
        for threshold, points in bands:
            if value <= threshold:
                return points
        return 0
    for threshold, points in bands:
        if value >= threshold:
            return points
    return 0


def compute_health_score(latest_metrics: dict[str, float]) -> dict:
    breakdown = []
    total = 0
    max_possible = 0
    for code, (weight, _, _) in _BANDS.items():
        max_possible += weight
        if code not in latest_metrics:
            breakdown.append({"metric_code": code, "points": 0, "weight": weight, "included": False})
            continue
        points = _score_metric(code, latest_metrics[code])
        total += points
        breakdown.append({"metric_code": code, "points": points, "weight": weight, "included": True})

    score = round(100 * total / max_possible) if max_possible else 0
    if score >= 80:
        rating = "Excellent"
    elif score >= 60:
        rating = "Good"
    elif score >= 40:
        rating = "Moderate"
    elif score >= 20:
        rating = "Weak"
    else:
        rating = "Poor"

    return {"score": score, "rating": rating, "breakdown": breakdown}


tool("health_score.compute", allowed_agents=["insight_reasoner"])(compute_health_score)
