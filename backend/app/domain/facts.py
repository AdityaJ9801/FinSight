"""Fact resolution: turns every mapped row into ONE value per (period, account).

Several facts routinely compete for one account -- the balance sheet's own line, the same
figure restated in a note, a line split in two ('Trade payables -- MSE' / '-- others'), a
section's component rows plus its 'Total ...' row, and occasionally a low-confidence guess.
Treating them uniformly (the old rule: keep the single highest-confidence fact, or blindly sum
the 'other' buckets) produced the failures seen on a real listed-company workbook: debt taken
from a loan note instead of the balance sheet, current borrowings of 6 instead of 14,038,
'other current assets' five times total current assets.

Resolution, per (period, account):
1. Source tier: primary statement rows beat supporting schedules (notes, ageing, loan lists);
   deterministic mappings (rule / section / context) beat memory, which beats LLM guesses.
   Supporting-schedule facts are used only for accounts the statements don't report.
2. Total-type accounts (Total assets, PAT, net cash from operations, ...) take one fact:
   a row labelled 'Total ...' first, then the most trustworthy.
3. Line accounts: a 'Total ...' row wins; else a row equal to the sum of the others (a
   stated subtotal); else the distinct rows are summed (a line presented in parts).
   Low-confidence (< 0.6) facts join only if nothing better exists.
4. The 'other' buckets are derived from the statement's own subtotals when present
   (other current assets = total current assets - cash - receivables - inventory), so every
   side of the balance sheet foots and every chart share is consistent with the totals.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.domain.coa import DUMPING_GROUND_ACCOUNTS
from app.models.dataset import FinancialFact

MIN_CONFIDENCE = 0.6
_METHOD_RANK = {"rule": 0, "context": 0, "section": 0, "prefix": 1, "memory": 2, "llm": 3}

# Accounts that are totals/subtotals by nature: never summed across rows.
_SINGLE_VALUE = {
    "BS.CA.TOTAL", "BS.NCA.TOTAL", "BS.TOTAL_ASSETS", "BS.CL.TOTAL", "BS.NCL.TOTAL", "BS.EQ.TOTAL",
    "BS.TOTAL_EQUITY_LIAB", "BS.TOTAL_LIABILITIES", "PL.TOTAL_INCOME", "PL.TOTAL_EXPENSES",
    "PL.GROSS_PROFIT", "PL.EBITDA",
    "PL.PBEIT", "PL.PBT", "PL.PAT", "PL.TOTAL_COMPREHENSIVE_INCOME", "PL.EPS_BASIC", "PL.EPS_DILUTED",
    "PL.REVENUE", "CF.OPERATING", "CF.INVESTING", "CF.FINANCING", "CF.NET_CHANGE", "CF.OPENING_CASH",
    "CF.CLOSING_CASH",
}

# bucket -> (subtotal, named components): bucket = subtotal - components
_DERIVED_BUCKETS = {
    "BS.CA.OTHER": ("BS.CA.TOTAL", ("BS.CA.CASH", "BS.CA.TRADE_RECEIVABLES", "BS.CA.INVENTORY")),
    "BS.NCA.OTHER": ("BS.NCA.TOTAL", ("BS.NCA.PPE",)),
    "BS.CL.OTHER": ("BS.CL.TOTAL", ("BS.CL.TRADE_PAYABLES", "BS.CL.SHORT_TERM_BORROWINGS")),
    "BS.NCL.OTHER": ("BS.NCL.TOTAL", ("BS.NCL.LONG_TERM_BORROWINGS",)),
}


@dataclass
class _Candidate:
    value: float
    confidence: float
    role: str
    method: str
    is_total: bool
    row_key: str

    @property
    def tier(self) -> tuple[int, int]:
        return (0 if self.role == "primary" else 1, _METHOD_RANK.get(self.method, 3))


def _candidate(f: FinancialFact) -> _Candidate:
    ref = f.source_ref or {}
    confidence = f.confidence if f.confidence is not None else 1.0
    # Facts written before provenance was recorded: treat as primary; infer the method.
    method = ref.get("method") or ("rule" if confidence >= 0.95 else "llm")
    row_key = f"{f.source_doc}:{ref.get('sheet', '')}:{ref.get('cell') or ref.get('row') or f.id}"
    return _Candidate(float(f.value), confidence, ref.get("role", "primary"), method, bool(ref.get("is_total")), row_key)


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0.005, abs_tol=1.0)


def _resolve_account(account_id: str, cands: list[_Candidate]) -> float | None:
    # one fact per source row (the same row can't count twice)
    by_row: dict[str, _Candidate] = {}
    for c in cands:
        if c.row_key not in by_row or c.confidence > by_row[c.row_key].confidence:
            by_row[c.row_key] = c
    cands = list(by_row.values())

    usable = [c for c in cands if c.confidence >= MIN_CONFIDENCE] or [max(cands, key=lambda c: c.confidence)]
    best_role = min(c.tier[0] for c in usable)
    usable = [c for c in usable if c.tier[0] == best_role]

    if account_id in _SINGLE_VALUE:
        return min(usable, key=lambda c: (c.tier[1], not c.is_total, -c.confidence)).value

    totals = [c for c in usable if c.is_total]
    if totals:
        return min(totals, key=lambda c: (c.tier[1], -c.confidence)).value
    if len(usable) > 2:
        for c in usable:  # a stated subtotal equal to the sum of its components
            if _close(c.value, sum(o.value for o in usable if o is not c)):
                return c.value
    if len(usable) == 2 and _close(usable[0].value, usable[1].value) and usable[0].row_key != usable[1].row_key:
        # the same figure stated twice (a line and its restatement) -- not two parts of it
        same_sheet = usable[0].row_key.rsplit(":", 1)[0] == usable[1].row_key.rsplit(":", 1)[0]
        if not same_sheet:
            return usable[0].value
    return sum(c.value for c in usable)


def _derive_buckets(f: dict[str, float]) -> None:
    for bucket, (subtotal, components) in _DERIVED_BUCKETS.items():
        if subtotal not in f:
            continue
        plug = f[subtotal] - sum(f.get(c, 0.0) for c in components)
        if plug >= -max(1.0, abs(f[subtotal]) * 0.005):
            f[bucket] = max(plug, 0.0)


def schedule_tieouts(dataset_version_id: str, resolved: dict[date, dict[str, float]]) -> list[dict]:
    """Supporting schedules are evidence, not ledger lines: where a note states a total for
    an account the statements also report (an inventory note's 'Total inventories', a
    borrowings note's totals), compare it with the statement figure. A mismatch is surfaced
    as a warning -- it points at a mapping or unit problem -- without changing the ledger."""
    facts = FinancialFact.query.filter_by(dataset_version=dataset_version_id).all()
    out = []
    seen = set()
    for f in facts:
        ref = f.source_ref or {}
        if ref.get("role") != "supporting" or not ref.get("is_total"):
            continue
        stated = resolved.get(f.period_end, {}).get(f.account_id)
        key = (f.period_end, f.account_id, ref.get("sheet"))
        if stated is None or key in seen:
            continue
        seen.add(key)
        ok = _close(stated, float(f.value))
        out.append({"check_code": "SCHEDULE_TIE", "status": "pass" if ok else "warn", "period_end": f.period_end,
                    "expected": stated, "actual": float(f.value), "diff": float(f.value) - stated,
                    "details": {"rule": f"{ref.get('sheet') or 'schedule'}: '{ref.get('label')}' = statement "
                                        f"{f.account_id}", "account_id": f.account_id}})
    return out


def load_facts_by_period(dataset_version_id: str) -> dict[date, dict[str, float]]:
    facts = FinancialFact.query.filter_by(dataset_version=dataset_version_id).all()
    grouped: dict[date, dict[str, list[_Candidate]]] = defaultdict(lambda: defaultdict(list))
    for f in facts:
        grouped[f.period_end][f.account_id].append(_candidate(f))

    by_period: dict[date, dict[str, float]] = {}
    for period, accounts in grouped.items():
        has_primary = any(c.role == "primary" for cands in accounts.values() for c in cands)
        resolved = {}
        for account_id, cands in accounts.items():
            if has_primary:
                cands = [c for c in cands if c.role == "primary"]
                if not cands:
                    continue
            if account_id in DUMPING_GROUND_ACCOUNTS:
                primary = [c for c in cands if c.role == "primary"] or cands
                resolved[account_id] = sum({c.row_key: c for c in primary}[k].value for k in {c.row_key for c in primary})
            else:
                value = _resolve_account(account_id, cands)
                if value is not None:
                    resolved[account_id] = value
        _derive_buckets(resolved)
        by_period[period] = resolved
    return by_period
