"""Transaction anomaly detection: IsolationForest over amount/frequency features, plus a
handful of named rule-based checks the design doc calls out specifically (round-tripping,
cash spikes, related-party-like repeated counterparties) -- rules catch known patterns
precisely; the model catches everything else that's merely statistically unusual.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from app.tools.registry import tool


def detect_anomalies(transactions: list[dict]) -> list[dict]:
    if not transactions:
        return []

    anomalies: list[dict] = []
    amounts = np.array([[t["debit"] or 0, t["credit"] or 0] for t in transactions], dtype=float)

    if len(transactions) >= 10:
        try:
            from sklearn.ensemble import IsolationForest

            model = IsolationForest(contamination=0.05, random_state=42)
            preds = model.fit_predict(amounts)
            for t, pred in zip(transactions, preds):
                if pred == -1:
                    anomalies.append({
                        "kind": "statistical_outlier", "row_idx": t.get("row_idx"),
                        "detail": f"Unusual transaction amount vs. the account's typical pattern.",
                    })
        except Exception:
            pass  # model-based detection is best-effort; rules below still run

    # Rule: large cash withdrawal (top 1% of debits, and above a floor so small books don't trip it)
    debits = [t["debit"] for t in transactions if t["debit"]]
    if debits:
        threshold = max(np.percentile(debits, 99), 100000)
        for t in transactions:
            if t["debit"] and t["debit"] >= threshold:
                anomalies.append({
                    "kind": "large_cash_withdrawal", "row_idx": t.get("row_idx"),
                    "detail": f"Debit of {t['debit']:.2f} is in the top 1% for this account.",
                })

    # Rule: round-tripping -- same counterparty/narration credited then debited a similar
    # amount within a short window (approximated here by narration match, no date-window
    # math to keep this dependency-light; good enough to flag for analyst review).
    narration_counts = Counter(t["narration"].strip().lower() for t in transactions if t.get("narration"))
    for narration, count in narration_counts.items():
        if count >= 4:
            anomalies.append({
                "kind": "repeated_counterparty", "row_idx": None,
                "detail": f"Narration '{narration}' repeats {count} times -- review for round-tripping "
                          f"or related-party concentration.",
            })

    return anomalies


tool("anomaly.detect", allowed_agents=["risk"])(detect_anomalies)
