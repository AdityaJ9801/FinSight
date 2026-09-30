"""Industry peer benchmarks: quartile ranges (p25 / median / p75) per ratio and sector,
used to place a company's latest ratios against its peers rather than only its own history.

The built-in table is INDICATIVE: typical ranges for Indian companies by sector, meant to
make the feature useful out of the box. It is not a licensed dataset and must not be the
sole basis of a credit decision. Point BENCHMARKS_FILE at a JSON file with the same shape to
use your own licensed data (e.g. CMIE Prowess or an internal loan-book study); it replaces
the built-in table entirely, and its "source" / "as_of" appear in the UI.

Units match the metric registry: "%" ratios are fractions (0.12 = 12%), "x" are multiples,
"days" are days.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

BUILT_IN_SOURCE = "FinSight indicative ranges (not a licensed dataset)"
BUILT_IN_AS_OF = "FY2024"

# Lower-is-better metrics; everything else benchmarked is higher-is-better.
LOWER_IS_BETTER = {"debt_to_equity", "dso", "dio", "cash_conversion_cycle"}

_Q = tuple[float, float, float]

_BUILT_IN: dict[str, dict] = {
    "manufacturing": {"label": "Manufacturing (diversified)", "metrics": {
        "current_ratio": (1.1, 1.45, 1.9), "quick_ratio": (0.7, 1.0, 1.4), "debt_to_equity": (0.2, 0.55, 1.1),
        "interest_coverage": (2.5, 5.0, 12.0), "gross_profit_pct": (0.22, 0.32, 0.42), "ebitda_margin": (0.08, 0.12, 0.17),
        "net_profit_margin": (0.03, 0.06, 0.10), "roe": (0.07, 0.12, 0.18), "roce": (0.09, 0.14, 0.20),
        "dso": (45, 65, 90), "dio": (50, 75, 110), "dpo": (40, 60, 85), "cash_conversion_cycle": (45, 80, 120),
        "asset_turnover": (0.8, 1.1, 1.5)}},
    "fmcg": {"label": "FMCG and consumer staples", "metrics": {
        "current_ratio": (1.0, 1.3, 1.8), "quick_ratio": (0.5, 0.8, 1.2), "debt_to_equity": (0.0, 0.1, 0.4),
        "interest_coverage": (10.0, 30.0, 80.0), "gross_profit_pct": (0.38, 0.48, 0.58), "ebitda_margin": (0.12, 0.18, 0.25),
        "net_profit_margin": (0.07, 0.11, 0.16), "roe": (0.15, 0.25, 0.40), "roce": (0.20, 0.32, 0.50),
        "dso": (10, 20, 35), "dio": (30, 45, 65), "dpo": (45, 65, 90), "cash_conversion_cycle": (-10, 10, 30),
        "asset_turnover": (1.2, 1.6, 2.1)}},
    "it_services": {"label": "IT and IT-enabled services", "metrics": {
        "current_ratio": (1.8, 2.6, 3.8), "quick_ratio": (1.8, 2.6, 3.8), "debt_to_equity": (0.0, 0.05, 0.25),
        "interest_coverage": (15.0, 40.0, 120.0), "gross_profit_pct": (0.30, 0.38, 0.46), "ebitda_margin": (0.15, 0.21, 0.27),
        "net_profit_margin": (0.09, 0.14, 0.19), "roe": (0.15, 0.22, 0.30), "roce": (0.20, 0.28, 0.38),
        "dso": (55, 70, 90), "dpo": (15, 25, 40), "asset_turnover": (0.8, 1.0, 1.3)}},
    "pharma": {"label": "Pharmaceuticals", "metrics": {
        "current_ratio": (1.4, 1.9, 2.7), "quick_ratio": (0.9, 1.3, 1.9), "debt_to_equity": (0.1, 0.3, 0.7),
        "interest_coverage": (5.0, 12.0, 30.0), "gross_profit_pct": (0.50, 0.60, 0.68), "ebitda_margin": (0.14, 0.20, 0.26),
        "net_profit_margin": (0.07, 0.12, 0.17), "roe": (0.10, 0.15, 0.21), "roce": (0.12, 0.18, 0.25),
        "dso": (60, 85, 115), "dio": (90, 120, 160), "dpo": (60, 85, 115), "cash_conversion_cycle": (90, 120, 160),
        "asset_turnover": (0.6, 0.85, 1.1)}},
    "auto_components": {"label": "Automobile and auto components", "metrics": {
        "current_ratio": (1.1, 1.4, 1.8), "quick_ratio": (0.7, 1.0, 1.3), "debt_to_equity": (0.2, 0.5, 1.0),
        "interest_coverage": (3.0, 7.0, 15.0), "gross_profit_pct": (0.28, 0.36, 0.44), "ebitda_margin": (0.10, 0.13, 0.17),
        "net_profit_margin": (0.04, 0.07, 0.10), "roe": (0.09, 0.14, 0.19), "roce": (0.11, 0.16, 0.22),
        "dso": (45, 60, 80), "dio": (35, 50, 70), "dpo": (50, 70, 95), "cash_conversion_cycle": (20, 40, 65),
        "asset_turnover": (1.0, 1.3, 1.7)}},
    "chemicals": {"label": "Chemicals", "metrics": {
        "current_ratio": (1.3, 1.7, 2.3), "quick_ratio": (0.8, 1.1, 1.6), "debt_to_equity": (0.1, 0.35, 0.8),
        "interest_coverage": (4.0, 10.0, 25.0), "gross_profit_pct": (0.30, 0.38, 0.46), "ebitda_margin": (0.12, 0.17, 0.22),
        "net_profit_margin": (0.06, 0.10, 0.14), "roe": (0.10, 0.15, 0.20), "roce": (0.12, 0.18, 0.24),
        "dso": (55, 75, 95), "dio": (55, 80, 110), "dpo": (50, 70, 95), "cash_conversion_cycle": (60, 85, 115),
        "asset_turnover": (0.8, 1.0, 1.3)}},
    "textiles": {"label": "Textiles and apparel", "metrics": {
        "current_ratio": (1.1, 1.35, 1.7), "quick_ratio": (0.5, 0.75, 1.0), "debt_to_equity": (0.4, 0.9, 1.6),
        "interest_coverage": (1.8, 3.5, 7.0), "gross_profit_pct": (0.20, 0.28, 0.36), "ebitda_margin": (0.07, 0.11, 0.15),
        "net_profit_margin": (0.01, 0.04, 0.07), "roe": (0.04, 0.09, 0.14), "roce": (0.07, 0.11, 0.15),
        "dso": (50, 75, 100), "dio": (70, 100, 140), "dpo": (35, 55, 80), "cash_conversion_cycle": (90, 120, 160),
        "asset_turnover": (0.8, 1.05, 1.3)}},
    "construction_infra": {"label": "Construction and infrastructure", "metrics": {
        "current_ratio": (1.1, 1.35, 1.7), "quick_ratio": (0.7, 1.0, 1.3), "debt_to_equity": (0.5, 1.0, 1.8),
        "interest_coverage": (1.8, 3.0, 5.5), "gross_profit_pct": (0.15, 0.22, 0.30), "ebitda_margin": (0.09, 0.13, 0.18),
        "net_profit_margin": (0.02, 0.05, 0.08), "roe": (0.05, 0.10, 0.15), "roce": (0.08, 0.12, 0.16),
        "dso": (70, 100, 140), "dio": (40, 70, 110), "dpo": (70, 100, 140), "cash_conversion_cycle": (50, 90, 140),
        "asset_turnover": (0.5, 0.75, 1.0)}},
    "trading_distribution": {"label": "Trading and distribution", "metrics": {
        "current_ratio": (1.1, 1.3, 1.6), "quick_ratio": (0.6, 0.85, 1.1), "debt_to_equity": (0.3, 0.8, 1.5),
        "interest_coverage": (2.0, 3.5, 6.0), "gross_profit_pct": (0.06, 0.10, 0.15), "ebitda_margin": (0.02, 0.04, 0.06),
        "net_profit_margin": (0.01, 0.02, 0.035), "roe": (0.08, 0.13, 0.18), "roce": (0.10, 0.15, 0.21),
        "dso": (30, 50, 70), "dio": (25, 45, 70), "dpo": (25, 40, 60), "cash_conversion_cycle": (30, 55, 85),
        "asset_turnover": (2.0, 3.0, 4.5)}},
    "retail": {"label": "Retail", "metrics": {
        "current_ratio": (0.9, 1.2, 1.6), "quick_ratio": (0.2, 0.4, 0.7), "debt_to_equity": (0.1, 0.5, 1.2),
        "interest_coverage": (2.0, 4.0, 9.0), "gross_profit_pct": (0.25, 0.33, 0.42), "ebitda_margin": (0.06, 0.09, 0.13),
        "net_profit_margin": (0.01, 0.03, 0.06), "roe": (0.06, 0.12, 0.18), "roce": (0.08, 0.13, 0.19),
        "dso": (2, 5, 12), "dio": (60, 90, 130), "dpo": (40, 60, 85), "cash_conversion_cycle": (25, 40, 70),
        "asset_turnover": (1.3, 1.9, 2.6)}},
}


@lru_cache(maxsize=1)
def load_benchmarks() -> dict:
    """{"source", "as_of", "industries": {key: {"label", "metrics": {code: (p25, p50, p75)}}}}."""
    path = os.environ.get("BENCHMARKS_FILE")
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {
            "source": data.get("source", Path(path).name),
            "as_of": data.get("as_of", ""),
            "industries": {k: {"label": v["label"], "metrics": {c: tuple(q) for c, q in v["metrics"].items()}}
                           for k, v in data["industries"].items()},
        }
    return {"source": BUILT_IN_SOURCE, "as_of": BUILT_IN_AS_OF, "industries": _BUILT_IN}


def industries() -> list[dict]:
    data = load_benchmarks()
    return [{"key": k, "label": v["label"]} for k, v in data["industries"].items()]


def compare(industry: str, latest: dict[str, tuple[str, float, str]]) -> dict | None:
    """latest: {metric_code: (period_end_iso, value, unit)}. Returns None for an unknown
    industry. Each item says which quartile the company sits in and whether that is
    better, in line with, or worse than the peer median band."""
    data = load_benchmarks()
    sector = data["industries"].get(industry)
    if sector is None:
        return None
    items = []
    for code, (p25, p50, p75) in sector["metrics"].items():
        if code not in latest:
            continue
        period, value, unit = latest[code]
        quartile = 1 if value < p25 else 2 if value < p50 else 3 if value < p75 else 4
        lower_better = code in LOWER_IS_BETTER
        if p25 <= value <= p75:
            verdict = "in_line"
        elif (value > p75) != lower_better:
            verdict = "better"
        else:
            verdict = "worse"
        items.append({"metric_code": code, "period_end": period, "value": value, "unit": unit,
                      "p25": p25, "median": p50, "p75": p75, "quartile": quartile,
                      "lower_is_better": lower_better, "verdict": verdict})
    return {"industry": industry, "label": sector["label"], "source": data["source"], "as_of": data["as_of"],
            "items": items}
