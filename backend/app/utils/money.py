"""One way to show money everywhere in a report: in the unit the source document uses.

The ledger stores full rupees (a '(₹ crore)' statement's 1,39,720.22 is stored as
1,397,202,200,000). Charts showed crores while tables, placeholders and the diagnostic
printed full rupees ('Rs. 13,97,20,22,00,000') -- the same number, but readers took it for
a 10^7 error. Every renderer now formats through format_money() with the job's display
scale, so a crore-denominated filing reads in crores throughout.
"""
from __future__ import annotations

import math
import threading

SUFFIXES = {1e9: "Bn", 1e7: "Cr", 1e6: "Mn", 1e5: "L", 1e3: "K"}
_local = threading.local()


def indian_group(value: float, decimals: int = 2) -> str:
    """1397202.2 -> '13,97,202.20' (Indian digit grouping)."""
    negative = value < 0
    value = abs(value)
    text = f"{value:.{decimals}f}"
    int_part, _, frac = text.partition(".")
    if len(int_part) > 3:
        last3, rest = int_part[-3:], int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        int_part = ",".join(groups) + "," + last3
    return ("-" if negative else "") + int_part + (f".{frac}" if frac else "")


def display_scale_for(dataset_version_id: str | None) -> float | None:
    """The unit the job's documents are stated in (largest wins when files differ), e.g.
    1e7 for a '(₹ crore)' filing. None when documents are in plain rupees/units."""
    if not dataset_version_id:
        return None
    from app.models.dataset import DatasetVersion
    from app.models.document import Document
    from app.extensions import db

    dsv = db.session.get(DatasetVersion, dataset_version_id)
    if dsv is None:
        return None
    scales = [float(d.unit_scale or 1) for d in Document.query.filter_by(job_id=dsv.job_id).all()]
    scale = max(scales, default=1.0)
    return scale if scale in SUFFIXES else None


def set_thread_scale(scale: float | None) -> None:
    """Chart rendering formats deep inside matplotlib callbacks; the chart agent sets the
    job's scale for its own thread once instead of threading it through every call."""
    _local.scale = scale


def thread_scale() -> float | None:
    return getattr(_local, "scale", None)


def format_money(value: float, scale: float | None = None, decimals: int = 2, prefix: str = "Rs ") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if scale is None:
        scale = thread_scale()
    sign, a = ("-" if value < 0 else ""), abs(value)  # '-Rs 3,984 Cr', not 'Rs -3,984 Cr'
    if scale and scale in SUFFIXES:
        return f"{sign}{prefix}{indian_group(a / scale, decimals)} {SUFFIXES[scale]}"
    # No stated unit: pick one per value, but never print a 10+ digit raw rupee figure.
    for s in (1e7, 1e5):
        if a >= s:
            return f"{sign}{prefix}{indian_group(a / s, decimals)} {SUFFIXES[s]}"
    return f"{sign}{prefix}{indian_group(a, 0)}"
