"""Layout fingerprinting: a hash of the (normalized) row-label structure so repeat exports
from the same source system/template are recognized automatically and reuse stored mappings
(design doc §2 principle 3, §6.4). Deliberately simple -- a header/label-set hash, not ML."""
from __future__ import annotations

import hashlib

from app.domain.coa import normalize_label
from app.tools.registry import tool


def fingerprint_layout(labels: list[str]) -> str:
    normalized = sorted({normalize_label(label) for label in labels if label.strip()})
    digest = hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()
    return digest[:24]


tool("layout.fingerprint", allowed_agents=["intake_classifier"])(fingerprint_layout)
