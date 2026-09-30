"""Regex-based PII masking applied to any text before it is sent to the LLM gateway
(design doc §9: "PII masking before LLM calls: PAN, Aadhaar, bank account numbers, phone
numbers, emails -> tokens; unmask only at render time where the user is authorized").

This is pattern-based, not a security boundary against a determined adversary -- it is
meant to keep obvious identifiers out of third-party LLM logs, matching the design intent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS = {
    "PAN": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "AADHAAR": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "PHONE": re.compile(r"\b(?:\+?91[-\s]?)?[6-9]\d{9}\b"),
    "BANK_ACCT": re.compile(r"\b\d{9,18}\b"),
}
# Order matters: more specific patterns (PAN, AADHAAR, EMAIL, PHONE) before the very broad
# BANK_ACCT digit-run pattern, so a 12-digit Aadhaar isn't first swallowed as a bank account.
_ORDER = ["PAN", "AADHAAR", "EMAIL", "PHONE", "BANK_ACCT"]


@dataclass
class MaskResult:
    masked_text: str
    token_map: dict = field(default_factory=dict)  # token -> original value


def mask(text: str) -> MaskResult:
    token_map: dict[str, str] = {}
    counter = 0

    def _sub(kind: str):
        nonlocal counter

        def repl(m: re.Match) -> str:
            nonlocal counter
            counter += 1
            token = f"[[{kind}_{counter}]]"
            token_map[token] = m.group(0)
            return token

        return repl

    masked = text
    for kind in _ORDER:
        masked = _PATTERNS[kind].sub(_sub(kind), masked)
    return MaskResult(masked_text=masked, token_map=token_map)


def unmask(text: str, token_map: dict) -> str:
    result = text
    for token, original in token_map.items():
        result = result.replace(token, original)
    return result
