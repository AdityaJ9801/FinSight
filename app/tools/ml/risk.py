"""Default/stress risk scoring: a transparent rules table over leverage/liquidity/coverage
metrics, mirroring the health-score approach so risk drivers are auditable rather than a
black-box model output (same rationale as calc/health_score.py, inverted: higher = riskier).
"""
from __future__ import annotations

from app.tools.registry import tool


def score_risk(metrics: dict[str, float]) -> dict:
    drivers = []
    risk_points = 0
    max_points = 0

    def add(code: str, weight: int, condition: bool, reason: str):
        nonlocal risk_points, max_points
        max_points += weight
        if code in metrics and condition:
            risk_points += weight
            drivers.append({"metric_code": code, "reason": reason, "weight": weight})

    if "debt_to_equity" in metrics:
        add("debt_to_equity", 25, metrics["debt_to_equity"] > 2.0, "High leverage (D/E > 2.0)")
    if "current_ratio" in metrics:
        add("current_ratio", 25, metrics["current_ratio"] < 1.0, "Current liabilities exceed current assets")
    if "interest_coverage" in metrics:
        add("interest_coverage", 25, metrics["interest_coverage"] < 1.5, "Thin interest coverage")
    if "net_profit_margin" in metrics:
        add("net_profit_margin", 15, metrics["net_profit_margin"] < 0, "Operating at a net loss")
    if "dso" in metrics:
        add("dso", 10, metrics["dso"] > 90, "Slow receivables collection (DSO > 90 days)")

    score = round(100 * risk_points / max_points) if max_points else 0
    if score >= 70:
        band = "high"
    elif score >= 40:
        band = "medium"
    else:
        band = "low"

    return {"risk_score": score, "band": band, "drivers": drivers}


tool("risk.score", allowed_agents=["risk"])(score_risk)
