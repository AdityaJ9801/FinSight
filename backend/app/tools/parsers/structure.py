"""Statement-structure awareness shared by the Excel and CSV parsers.

Real statements are not flat label/value lists:
- value-less heading rows ('Non-current liabilities', 'Financial liabilities',
  'Exceptional items:') give the rows beneath them their meaning -- 'Borrowings' under
  Non-current liabilities is long-term debt, under Current liabilities it's short-term debt;
- a sheet can hold several sub-tables whose columns are NOT periods (ageing buckets
  'Not Due | < 6 months', a debenture list 'Coupon | No. of debentures'); reading those
  cells as if they were the sheet's period columns manufactured facts out of ageing
  buckets and coupon rates.

SectionTracker keeps the heading path; `period_like` decides whether a sub-table header's
columns are reporting periods.
"""
from __future__ import annotations

import re

from app.domain.coa import is_total_label, normalize_label

_PERIOD_HINT = re.compile(r"\b(?:19|20)\d{2}\b|\bFY\s*'?\d{2,4}\b|\b(?:Q[1-4]|H[12])\b", re.IGNORECASE)

# Headings that open a top-level section of a statement (anything else is a sub-heading
# nested under the current top-level section).
_MAJOR = re.compile(
    r"^(?:non[- ]current (?:assets|liabilities)|current (?:assets|liabilities)|equity|assets|liabilities|"
    r"equity and liabilities|income|revenue|expenses|expenditure|exceptional items?|tax expenses?|"
    r"income tax expenses?|other comprehensive income|earnings per (?:equity )?share|"
    r"\(?[a-d]\)? ?cash flows? (?:from|used in)|cash flows? from)",
)


def period_like(text) -> bool:
    return bool(text) and bool(_PERIOD_HINT.search(str(text)))


def leading_indent(raw_label: str) -> int:
    return len(raw_label) - len(raw_label.lstrip(" \t"))


class SectionTracker:
    def __init__(self):
        self.root: str | None = None   # ALL-CAPS banner, e.g. 'EQUITY AND LIABILITIES'
        self.major: str | None = None  # e.g. 'Current liabilities'
        self.minor: str | None = None  # e.g. 'Financial liabilities'
        self.minor_indent = 0
        self._children_indented = False

    def heading(self, raw_label: str, indent: int) -> None:
        label = raw_label.strip().rstrip(":").strip()
        if not label:
            return
        norm = normalize_label(label)
        letters = [c for c in label if c.isalpha()]
        if letters and all(c.isupper() for c in letters) and len(letters) > 3:
            self.root, self.major, self.minor = label, None, None
        elif _MAJOR.match(norm):
            self.major, self.minor = label, None
        else:
            self.minor, self.minor_indent, self._children_indented = label, indent, False

    def data_row(self, raw_label: str, indent: int) -> str:
        """Section path for a data row; also closes sub-groups and sections as they end."""
        if self.minor is not None:
            if indent > self.minor_indent:
                self._children_indented = True
            elif self._children_indented:
                # back at the sub-heading's own indentation after indented children: the
                # sub-group ended ('Provisions' after '  Borrowings', '  Lease liabilities'
                # under 'Financial liabilities')
                self.minor, self._children_indented = None, False
        path = " > ".join(p for p in (self.root, self.major, self.minor) if p)
        if is_total_label(raw_label):  # 'Total current liabilities' closes 'Current liabilities'
            n = normalize_label(raw_label)
            if self.major and normalize_label(self.major) in n:
                self.major, self.minor = None, None
            elif self.minor and normalize_label(self.minor) in n:
                self.minor = None
        return path
