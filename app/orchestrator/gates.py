"""Stage-gate predicates (design doc's DAG diagram, §5 steps 7/9/11). Kept as named
functions -- even though today each just reads a boolean a supervisor already computed --
so the gate condition has one obvious place to find and to make stricter later (e.g.
requiring a minimum confidence, not just "no open reviews").
"""
from __future__ import annotations


def data_gate_passed(dataset_version_status: str) -> bool:
    return dataset_version_status in ("VALIDATED", "VALIDATED_WITH_GAPS")


def analysis_gate_passed(modules_done: int) -> bool:
    return modules_done > 0


def delivery_gate_passed(verifier_passed: bool) -> bool:
    return verifier_passed
