from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.domain.coa import DUMPING_GROUND_ACCOUNTS
from app.models.dataset import FinancialFact


def load_facts_by_period(dataset_version_id: str) -> dict[date, dict[str, float]]:
    """Two different aggregation rules per (period, account_id), depending on the account:

    - DUMPING_GROUND_ACCOUNTS (BS.*.OTHER): several distinct, unrelated rows legitimately
      land here (mapper.py's own low-confidence fallback target), so they're summed. An
      overwrite here silently discarded all but the last such row for every ratio/metric/
      reconciliation check that reads this -- a real, confirmed-live correctness bug.
    - Every other account is a specific Schedule III statement line that should appear at
      most once per period -- takes the highest-confidence single fact instead of summing.
      Confirmed live: summing here let low-confidence LLM mappings of unrelated disclosure
      rows (e.g. a P&L sheet's Other Comprehensive Income / tax-reconciliation notes) pile
      into the same named account as the real line item, corrupting it."""
    facts = FinancialFact.query.filter_by(dataset_version=dataset_version_id).all()
    by_period: dict[date, dict[str, float]] = defaultdict(dict)
    best_confidence: dict[tuple[date, str], float] = {}
    for f in facts:
        bucket = by_period[f.period_end]
        if f.account_id in DUMPING_GROUND_ACCOUNTS:
            bucket[f.account_id] = bucket.get(f.account_id, 0.0) + float(f.value)
            continue
        key = (f.period_end, f.account_id)
        confidence = f.confidence if f.confidence is not None else 1.0
        if key not in best_confidence or confidence > best_confidence[key]:
            best_confidence[key] = confidence
            bucket[f.account_id] = float(f.value)
    return dict(by_period)
