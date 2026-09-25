from dataclasses import dataclass, field


@dataclass
class RawRow:
    row_idx: int
    label: str
    values: dict  # period_key (str) -> float
    is_header: bool = False
    is_subtotal: bool = False
    indent_level: int = 0
    source_ref: dict = field(default_factory=dict)


@dataclass
class RawTable:
    rows: list  # list[RawRow]
    periods: list  # list[str], column order
    name: str = ""  # sheet name / page label, for provenance/debugging
