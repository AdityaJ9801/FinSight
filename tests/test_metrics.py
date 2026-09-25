from datetime import date

from app.tools.calc.metrics import compute_all
from app.tools.calc.health_score import compute_health_score


def test_current_ratio_and_gate_metrics():
    facts = {
        date(2024, 3, 31): {
            "BS.CA.TOTAL": 4750000, "BS.CL.TOTAL": 2250000, "BS.CA.INVENTORY": 1100000,
            "BS.CA.CASH": 1500000, "BS.CA.TRADE_RECEIVABLES": 1800000, "BS.CL.TRADE_PAYABLES": 1300000,
            "PL.REVENUE": 12000000, "PL.COGS": 7000000, "PL.OTHER_INCOME": 120000,
            "PL.EMPLOYEE_COST": 1800000, "PL.OTHER_EXPENSES": 900000, "PL.PAT": 1365000,
            "BS.EQ.TOTAL": 6165000, "BS.TOTAL_ASSETS": 11500000,
        }
    }
    results = compute_all(facts)
    by_code = {r["metric_code"]: r["value"] for r in results}

    assert round(by_code["current_ratio"], 4) == round(4750000 / 2250000, 4)
    assert round(by_code["net_profit_margin"], 4) == round(1365000 / 12000000, 4)
    assert "quick_ratio" in by_code


def test_revenue_growth_needs_two_periods():
    facts = {
        date(2023, 3, 31): {"PL.REVENUE": 10000000},
        date(2024, 3, 31): {"PL.REVENUE": 12000000},
    }
    results = compute_all(facts)
    growth = next(r for r in results if r["metric_code"] == "revenue_growth_yoy")
    assert round(growth["value"], 4) == round(0.2, 4)


def test_health_score_bands():
    good = compute_health_score({
        "current_ratio": 2.5, "debt_to_equity": 0.3, "net_profit_margin": 0.18,
        "interest_coverage": 6.0, "dso": 20,
    })
    assert good["score"] == 100
    assert good["rating"] == "Excellent"

    poor = compute_health_score({
        "current_ratio": 0.5, "debt_to_equity": 4.0, "net_profit_margin": -0.1,
        "interest_coverage": 0.5, "dso": 150,
    })
    assert poor["score"] == 0
    assert poor["rating"] == "Poor"
